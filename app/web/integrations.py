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
    
    if connection and connection.is_active:
        from app.integrations.quickbooks_service import QuickBooksService
        qb = QuickBooksService(current_user)
        result = qb.get_accounts(connection)
        if result.get('QueryResponse', {}).get('Account'):
            accounts = result['QueryResponse']['Account']
    
    return render_template('integrations/quickbooks.html', 
                         connection=connection, 
                         accounts=accounts)


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
    connection.auto_sync = request.form.get('auto_sync') == 'on'
    
    db.session.commit()
    
    flash('QuickBooks settings updated.', 'success')
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/sync/<int:invoice_id>', methods=['POST'])
@login_required
def quickbooks_sync_invoice(invoice_id):
    """Sync a single invoice to QuickBooks"""
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
