"""QuickBooks Integration Routes"""
from flask import Blueprint, redirect, request, jsonify, render_template, flash, url_for, session, current_app
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import secrets

bp = Blueprint('integrations', __name__, url_prefix='/integrations')


@bp.route('/quickbooks/connect')
@login_required
def quickbooks_connect():
    """Initiate QuickBooks OAuth flow"""
    from app.integrations.quickbooks_service import QuickBooksService
    
    qb = QuickBooksService()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    session['qb_oauth_state'] = state
    
    auth_url = qb.get_auth_url(state=state)
    return redirect(auth_url)


@bp.route('/quickbooks/callback')
@login_required
def quickbooks_callback():
    """Handle QuickBooks OAuth callback"""
    from app.integrations.quickbooks_service import QuickBooksService
    from app.models.quickbooks import QuickBooksConnection
    from app.extensions import db
    
    # Verify state
    state = request.args.get('state')
    if state != session.get('qb_oauth_state'):
        flash('Invalid OAuth state. Please try again.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Check for errors
    error = request.args.get('error')
    if error:
        flash(f'QuickBooks authorization failed: {error}', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Get authorization code
    auth_code = request.args.get('code')
    realm_id = request.args.get('realmId')
    
    if not auth_code or not realm_id:
        flash('Missing authorization code or realm ID.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Exchange code for tokens
    qb = QuickBooksService()
    tokens = qb.exchange_code_for_tokens(auth_code)
    
    if not tokens:
        flash('Failed to exchange authorization code for tokens.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Check if connection already exists for this user
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection:
        # Update existing connection
        connection.realm_id = realm_id
        connection.access_token = tokens['access_token']
        connection.refresh_token = tokens['refresh_token']
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
        connection.is_active = True
    else:
        # Create new connection
        connection = QuickBooksConnection(
            user_id=current_user.id,
            realm_id=realm_id,
            access_token=tokens['access_token'],
            refresh_token=tokens['refresh_token'],
            token_expires_at=datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
        )
        db.session.add(connection)
    
    db.session.commit()
    
    # Get company info
    qb_service = QuickBooksService(current_user)
    company_info = qb_service.get_company_info(connection)
    
    if company_info.get('CompanyInfo'):
        connection.company_name = company_info['CompanyInfo'].get('CompanyName')
        db.session.commit()
    
    flash(f'Successfully connected to QuickBooks: {connection.company_name or realm_id}', 'success')
    # If user is in setup wizard, return there
    if not current_user.setup_completed:
        return redirect(url_for('setup.step', step=2))
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/disconnect', methods=['POST'])
@login_required
def quickbooks_disconnect():
    """Disconnect QuickBooks"""
    from app.models.quickbooks import QuickBooksConnection
    from app.extensions import db
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection:
        db.session.delete(connection)
        db.session.commit()
        flash('QuickBooks disconnected successfully.', 'success')
    
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/settings')
@login_required
def quickbooks_settings():
    """QuickBooks settings page"""
    from app.models.quickbooks import QuickBooksConnection
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    accounts = []
    income_accounts = []
    
    if connection and connection.is_active:
        from app.integrations.quickbooks_service import QuickBooksService
        qb = QuickBooksService(current_user)
        
        # Get expense accounts
        result = qb.get_accounts(connection)
        if result.get('QueryResponse', {}).get('Account'):
            accounts = result['QueryResponse']['Account']
        
        # Get income accounts
        income_result = qb.get_income_accounts(connection)
        if income_result.get('QueryResponse', {}).get('Account'):
            income_accounts = income_result['QueryResponse']['Account']
    
    return render_template('integrations/quickbooks.html', 
                         connection=connection, 
                         accounts=accounts,
                         income_accounts=income_accounts)


@bp.route('/quickbooks/settings/update', methods=['POST'])
@login_required
def quickbooks_update_settings():
    """Update QuickBooks settings"""
    from app.models.quickbooks import QuickBooksConnection
    from app.extensions import db
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if not connection:
        return jsonify({'success': False, 'error': 'Not connected to QuickBooks'}), 400
    
    # Update settings
    connection.default_expense_account_id = request.form.get('expense_account_id')
    connection.default_expense_account_name = request.form.get('expense_account_name')
    connection.default_income_account_id = request.form.get('income_account_id')
    connection.default_income_account_name = request.form.get('income_account_name')
    connection.auto_sync = request.form.get('auto_sync') == 'on'
    
    db.session.commit()
    
    flash('QuickBooks settings updated.', 'success')
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/sync/<int:invoice_id>', methods=['POST'])
@login_required
def quickbooks_sync_invoice(invoice_id):
    """Sync a single invoice to QuickBooks as a Bill"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please set a default expense account in QuickBooks settings'}), 400
    
    # Sync to QuickBooks
    qb = QuickBooksService(current_user)
    result = qb.sync_invoice_to_quickbooks(connection, invoice)
    
    if result.get('success'):
        return jsonify({
            'success': True, 
            'message': f'Invoice synced to QuickBooks as Bill #{result["bill_id"]}'
        })
    else:
        return jsonify({'success': False, 'error': result.get('error')}), 400


@bp.route('/quickbooks/sync-products/<int:invoice_id>', methods=['POST'])
@login_required
def quickbooks_sync_products(invoice_id):
    """Sync invoice line items as Products/Services in QuickBooks"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_income_account_id:
        return jsonify({'success': False, 'error': 'Please set a default income account in QuickBooks settings'}), 400
    
    if not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please set a default expense account in QuickBooks settings'}), 400
    
    # Sync products to QuickBooks
    qb = QuickBooksService(current_user)
    result = qb.sync_invoice_items_as_products(connection, invoice)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'message': f"Synced {result['synced']} products to QuickBooks ({result['skipped']} skipped)",
            'details': result
        })
    else:
        return jsonify({
            'success': False,
            'message': f"Synced {result['synced']} products, {result['failed']} failed",
            'details': result
        }), 400


@bp.route('/quickbooks/sync/bulk', methods=['POST'])
@login_required
def quickbooks_sync_bulk():
    """Sync multiple invoices to QuickBooks"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    invoice_ids = request.json.get('invoice_ids', [])
    
    if not invoice_ids:
        return jsonify({'success': False, 'error': 'No invoices selected'}), 400
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please set a default expense account in QuickBooks settings'}), 400
    
    qb = QuickBooksService(current_user)
    
    results = {'synced': 0, 'failed': 0, 'errors': []}
    
    for invoice_id in invoice_ids:
        invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
        if invoice:
            result = qb.sync_invoice_to_quickbooks(connection, invoice)
            if result.get('success'):
                results['synced'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"Invoice {invoice_id}: {result.get('error')}")
    
    return jsonify({
        'success': True,
        'message': f"Synced {results['synced']} invoices, {results['failed']} failed",
        'details': results
    })


@bp.route('/api/quickbooks/status')
@login_required
def quickbooks_status():
    """Get QuickBooks connection status"""
    from app.models.quickbooks import QuickBooksConnection
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection and connection.is_active:
        return jsonify({
            'connected': True,
            'company_name': connection.company_name,
            'realm_id': connection.realm_id,
            'auto_sync': connection.auto_sync,
            'last_sync_at': connection.last_sync_at.isoformat() if connection.last_sync_at else None
        })
    
    return jsonify({'connected': False})


@bp.route('/api/quickbooks/customers')
@login_required
def quickbooks_customers():
    """Get all QuickBooks customers"""
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'error': 'QuickBooks not connected'}), 400
    
    qb = QuickBooksService(current_user)
    result = qb.get_customers(connection)
    
    customers = result.get('QueryResponse', {}).get('Customer', [])
    
    return jsonify({
        'customers': [
            {
                'Id': c.get('Id'), 
                'DisplayName': c.get('DisplayName'),
                'FullyQualifiedName': c.get('FullyQualifiedName'),
                'ParentRef': c.get('ParentRef')
            }
            for c in customers
        ]
    })


@bp.route('/api/quickbooks/match-customer')
@login_required
def quickbooks_match_customer():
    """Match job reference to QuickBooks customer using Claude"""
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    job_reference = request.args.get('job_reference', '')
    
    if not job_reference:
        return jsonify({'matches': []})
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'error': 'QuickBooks not connected'}), 400
    
    qb = QuickBooksService(current_user)
    matches = qb.match_customer_to_job_reference(connection, job_reference)
    
    return jsonify({'matches': matches})


@bp.route('/api/quickbooks/draft-invoices')
@login_required
def quickbooks_draft_invoices():
    """Get draft invoices for a customer"""
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    customer_id = request.args.get('customer_id')
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'error': 'QuickBooks not connected'}), 400
    
    qb = QuickBooksService(current_user)
    drafts = qb.get_draft_invoices(connection, customer_id)
    
    return jsonify({
        'drafts': [
            {
                'Id': d.get('Id'),
                'DocNumber': d.get('DocNumber'),
                'TotalAmt': d.get('TotalAmt'),
                'Balance': d.get('Balance')
            }
            for d in drafts
        ]
    })


@bp.route('/quickbooks/sync-to-customer/<int:invoice_id>', methods=['POST'])
@login_required
def quickbooks_sync_to_customer(invoice_id):
    """Sync invoice to customer - updates products AND creates/adds to QB invoice"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    data = request.get_json() or {}
    customer_id = data.get('customer_id')
    
    if not customer_id:
        return jsonify({'success': False, 'error': 'Customer ID required'}), 400
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_income_account_id or not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please configure income and expense accounts in QuickBooks settings'}), 400
    
    # Perform full sync
    qb = QuickBooksService(current_user)
    result = qb.sync_invoice_to_customer(connection, invoice, customer_id)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'products_synced': result.get('products_synced', 0),
            'products_failed': result.get('products_failed', 0),
            'invoice_action': result.get('invoice_action'),
            'qb_invoice_id': result.get('qb_invoice_id'),
            'qb_invoice_number': result.get('qb_invoice_number')
        })
    else:
        return jsonify({
            'success': False,
            'error': '; '.join(result.get('errors', ['Unknown error']))
        }), 400
