"""QuickBooks Integration Routes"""
from flask import Blueprint, redirect, request, jsonify, render_template, flash, url_for, session, current_app
from flask_login import login_required, current_user, login_user
from datetime import datetime, timedelta
import secrets
import hashlib
import hmac
import os

bp = Blueprint('integrations', __name__, url_prefix='/integrations')


@bp.route('/overview')
@login_required
def integrations_overview():
    """Combined integrations overview page"""
    from app.models.quickbooks import QuickBooksConnection
    from app.models.xero import XeroConnection
    
    # Check QuickBooks connection
    qb_connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    qb_connected = qb_connection and qb_connection.is_active
    
    # Check Xero connection
    xero_connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    xero_connected = xero_connection and xero_connection.is_active
    
    return render_template('integrations/overview.html',
                         quickbooks_connected=qb_connected,
                         quickbooks_connection=qb_connection,
                         xero_connected=xero_connected,
                         xero_connection=xero_connection)


def generate_oauth_state(user_id):
    """Generate a secure OAuth state that includes the user ID.
    
    Format: {user_id}:{random_token}:{signature}
    The signature prevents tampering with the user_id.
    """
    secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key')
    random_token = secrets.token_urlsafe(16)
    
    # Create message to sign
    message = f"{user_id}:{random_token}"
    
    # Create HMAC signature
    signature = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()[:16]  # Use first 16 chars for brevity
    
    return f"{user_id}:{random_token}:{signature}"


def verify_oauth_state(state):
    """Verify the OAuth state and extract the user ID.
    
    Returns the user_id if valid, None if invalid.
    """
    if not state:
        return None
    
    try:
        parts = state.split(':')
        if len(parts) != 3:
            return None
        
        user_id, random_token, provided_signature = parts
        user_id = int(user_id)
        
        # Recreate the expected signature
        secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key')
        message = f"{user_id}:{random_token}"
        expected_signature = hmac.new(
            secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        
        # Constant-time comparison to prevent timing attacks
        if hmac.compare_digest(provided_signature, expected_signature):
            return user_id
        
        return None
    except (ValueError, TypeError):
        return None


# =============================================================================
# QUICKBOOKS ROUTES
# =============================================================================

@bp.route('/quickbooks/connect')
@login_required
def quickbooks_connect():
    """Initiate QuickBooks OAuth flow"""
    from app.integrations.quickbooks_service import QuickBooksService
    
    qb = QuickBooksService()
    
    # Generate state that includes user ID (doesn't rely on session persistence)
    state = generate_oauth_state(current_user.id)
    
    # Also store in session as backup (may or may not persist)
    session['qb_oauth_state'] = state
    session['qb_oauth_user_id'] = current_user.id
    session.modified = True
    
    current_app.logger.info(f"Starting QuickBooks OAuth for user {current_user.id}")
    
    auth_url = qb.get_auth_url(state=state)
    return redirect(auth_url)


@bp.route('/quickbooks/callback')
def quickbooks_callback():
    """Handle QuickBooks OAuth callback
    
    This route does NOT have @login_required because the session
    may not persist through the OAuth redirect. Instead, we extract
    the user ID from the signed state parameter.
    """
    from app.integrations.quickbooks_service import QuickBooksService
    from app.models.quickbooks import QuickBooksConnection
    from app.models.user import User
    from app.extensions import db
    
    # Get state from callback
    state = request.args.get('state')
    
    current_app.logger.info(f"QuickBooks callback received")
    
    # Verify state and extract user ID
    user_id = verify_oauth_state(state)
    
    if not user_id:
        current_app.logger.warning("Invalid OAuth state received in QuickBooks callback")
        flash('Invalid OAuth state. Please try again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get the user
    user = User.query.get(user_id)
    if not user:
        current_app.logger.warning(f"User {user_id} not found for QuickBooks callback")
        flash('User not found. Please log in and try again.', 'error')
        return redirect(url_for('auth.login'))
    
    current_app.logger.info(f"QuickBooks callback verified for user {user_id}")
    
    # Log the user in
    login_user(user)
    
    # Check for errors from QuickBooks
    error = request.args.get('error')
    if error:
        flash(f'QuickBooks authorization failed: {error}', 'error')
        if not user.setup_completed:
            return redirect(url_for('setup.step', step=2))
        return redirect(url_for('settings.settings_page'))
    
    # Get authorization code
    auth_code = request.args.get('code')
    realm_id = request.args.get('realmId')
    
    if not auth_code or not realm_id:
        flash('Missing authorization code or realm ID.', 'error')
        if not user.setup_completed:
            return redirect(url_for('setup.step', step=2))
        return redirect(url_for('settings.settings_page'))
    
    # Exchange code for tokens
    qb = QuickBooksService()
    tokens = qb.exchange_code_for_tokens(auth_code)
    
    if not tokens:
        flash('Failed to exchange authorization code for tokens.', 'error')
        if not user.setup_completed:
            return redirect(url_for('setup.step', step=2))
        return redirect(url_for('settings.settings_page'))
    
    # Encrypt tokens before storing
    encrypted_access = QuickBooksService.encrypt_token(tokens['access_token'])
    encrypted_refresh = QuickBooksService.encrypt_token(tokens['refresh_token'])
    
    # Check if connection already exists for this user
    connection = QuickBooksConnection.query.filter_by(user_id=user.id).first()
    
    if connection:
        # Update existing connection
        connection.realm_id = realm_id
        connection.access_token = encrypted_access
        connection.refresh_token = encrypted_refresh
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
        connection.is_active = True
    else:
        # Create new connection
        connection = QuickBooksConnection(
            user_id=user.id,
            realm_id=realm_id,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            token_expires_at=datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 3600))
        )
        db.session.add(connection)
    
    db.session.commit()
    
    # Get company info
    qb_service = QuickBooksService(user)
    company_info = qb_service.get_company_info(connection)
    
    if company_info.get('CompanyInfo'):
        connection.company_name = company_info['CompanyInfo'].get('CompanyName')
        db.session.commit()
    
    # Clear OAuth session data (if it exists)
    session.pop('qb_oauth_state', None)
    session.pop('qb_oauth_user_id', None)
    
    current_app.logger.info(f"Successfully connected QuickBooks for user {user.id}: {connection.company_name}")
    
    flash(f'Successfully connected to QuickBooks: {connection.company_name or realm_id}', 'success')
    
    # If user is in setup wizard, return there
    if not user.setup_completed:
        return redirect(url_for('setup.step', step=2))
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/disconnect', methods=['POST'])
@login_required
def quickbooks_disconnect():
    """
    Disconnect QuickBooks - proper flow required by Intuit:
    1. Revoke OAuth tokens via Intuit's revocation endpoint
    2. Clear stored tokens and mark connection inactive
    3. Retain the connection record (so user can reconnect easily)
    """
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    from app.extensions import db
    
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection:
        # Step 1: Revoke tokens with Intuit (best effort - don't block disconnect on failure)
        try:
            qb = QuickBooksService(current_user)
            revoked = qb.revoke_token(connection.refresh_token)
            if revoked:
                current_app.logger.info(f"Successfully revoked QB tokens for user {current_user.id}")
            else:
                current_app.logger.warning(f"Token revocation returned false for user {current_user.id} - proceeding with disconnect")
        except Exception as e:
            current_app.logger.warning(f"Token revocation failed for user {current_user.id}: {type(e).__name__} - proceeding with disconnect")
        
        # Step 2: Clear tokens and deactivate (keep the record for reconnect)
        connection.access_token = ''
        connection.refresh_token = ''
        connection.token_expires_at = None
        connection.is_active = False
        db.session.commit()
        
        current_app.logger.info(f"QuickBooks disconnected for user {current_user.id}")
        flash('QuickBooks disconnected successfully.', 'success')
    
    return redirect(url_for('integrations.quickbooks_settings'))


@bp.route('/quickbooks/reconnect')
@login_required
def quickbooks_reconnect():
    """
    Reconnect URL - Required by Intuit App Store (mandatory since Jan 2026).
    
    This endpoint handles the scenario where a user's OAuth connection has expired
    or been invalidated and they need to re-authorise. Intuit may link directly to 
    this URL from the QuickBooks App Store or from within QuickBooks Online.
    
    The flow:
    1. Check if user has an existing (inactive) connection
    2. Show a friendly reconnect page OR redirect straight to OAuth
    3. On successful callback, reactivate the existing connection
    """
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    # Check existing connection state
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection and connection.is_active:
        # Already connected - verify it still works
        qb = QuickBooksService(current_user)
        test = qb.get_company_info(connection)
        
        if not test.get('error'):
            flash('Your QuickBooks account is already connected and working.', 'info')
            return redirect(url_for('integrations.quickbooks_settings'))
        
        # Connection exists but is stale - mark inactive and proceed to re-auth
        current_app.logger.info(f"QuickBooks connection stale for user {current_user.id}, initiating reconnect")
        connection.is_active = False
        from app.extensions import db
        db.session.commit()
    
    # Initiate fresh OAuth flow
    return redirect(url_for('integrations.quickbooks_connect'))


@bp.route('/quickbooks/app-disconnect', methods=['POST'])
def quickbooks_app_disconnect():
    """
    Handle disconnect initiated from QuickBooks App Store side.
    
    When a user disconnects your app from within QuickBooks Online or the
    App Store, Intuit sends a webhook/notification. This endpoint handles
    that event by cleaning up the local connection.
    
    Intuit may also call this when revoking access during security reviews.
    
    Note: This endpoint does NOT require @login_required because it's called
    by Intuit's servers, not by the user's browser.
    """
    from app.models.quickbooks import QuickBooksConnection
    from app.extensions import db
    
    # Verify the request is from Intuit
    # Intuit sends the realmId in the payload
    data = request.get_json(silent=True) or {}
    realm_id = data.get('realmId') or request.args.get('realmId')
    
    # Also check Intuit's webhook signature if available
    intuit_signature = request.headers.get('intuit-signature')
    verifier_token = os.getenv('QUICKBOOKS_WEBHOOK_VERIFIER_TOKEN')
    
    if verifier_token and intuit_signature:
        # Verify webhook signature
        import base64
        expected_signature = base64.b64encode(
            hmac.new(
                verifier_token.encode(),
                request.get_data(),
                hashlib.sha256
            ).digest()
        ).decode()
        
        if not hmac.compare_digest(intuit_signature, expected_signature):
            current_app.logger.warning("Invalid Intuit webhook signature on app-disconnect")
            return jsonify({'error': 'Invalid signature'}), 401
    
    if not realm_id:
        current_app.logger.warning("App disconnect called without realmId")
        return jsonify({'error': 'realmId required'}), 400
    
    # Find and deactivate the connection for this realm
    connection = QuickBooksConnection.query.filter_by(realm_id=realm_id).first()
    
    if connection:
        connection.access_token = ''
        connection.refresh_token = ''
        connection.token_expires_at = None
        connection.is_active = False
        db.session.commit()
        current_app.logger.info(f"App-side disconnect processed for realm {realm_id}, user {connection.user_id}")
    else:
        current_app.logger.info(f"App disconnect for unknown realm {realm_id} - no action needed")
    
    return jsonify({'status': 'ok'}), 200


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
    
    if not connection.default_expense_account_id or not connection.default_income_account_id:
        return jsonify({'success': False, 'error': 'Please configure income and expense accounts in QuickBooks settings'}), 400
    
    # Sync products
    qb = QuickBooksService(current_user)
    result = qb.sync_invoice_items_as_products(connection, invoice)
    
    return jsonify(result)


@bp.route('/quickbooks/bulk-sync', methods=['POST'])
@login_required
def quickbooks_bulk_sync():
    """Sync multiple invoices to QuickBooks"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    data = request.get_json() or {}
    invoice_ids = data.get('invoice_ids', [])
    
    if not invoice_ids:
        return jsonify({'success': False, 'error': 'No invoices selected'}), 400
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please set a default expense account'}), 400
    
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
    from app.extensions import db
    
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
        # Update invoice sync status
        invoice.qb_synced_at = datetime.utcnow()
        db.session.commit()
        
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


@bp.route('/quickbooks/create-estimate/<int:quote_id>', methods=['POST'])
@login_required
def quickbooks_create_estimate(quote_id):
    """Create a QuickBooks Estimate from a GoZappify quote"""
    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.integrations.quickbooks_service import QuickBooksService
    
    data = request.get_json() or {}
    customer_id = data.get('customer_id')
    
    if not customer_id:
        return jsonify({'success': False, 'error': 'Customer ID required'}), 400
    
    # Get quote (stored in Invoice table with document_type='quote')
    quote = Invoice.query.filter_by(id=quote_id, user_id=current_user.id, document_type='quote').first()
    if not quote:
        return jsonify({'success': False, 'error': 'Quote not found'}), 404
    
    # Get QuickBooks connection
    connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'QuickBooks not connected'}), 400
    
    if not connection.default_income_account_id or not connection.default_expense_account_id:
        return jsonify({'success': False, 'error': 'Please configure income and expense accounts in QuickBooks settings'}), 400
    
    # Create estimate in QuickBooks
    qb = QuickBooksService(current_user)
    result = qb.sync_quote_to_estimate(connection, quote, customer_id)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'products_synced': result.get('products_synced', 0),
            'products_failed': result.get('products_failed', 0),
            'qb_estimate_id': result.get('qb_estimate_id'),
            'qb_estimate_number': result.get('qb_estimate_number')
        })
    else:
        return jsonify({
            'success': False,
            'error': '; '.join(result.get('errors', ['Unknown error']))
        }), 400


# =============================================================================
# XERO ROUTES (unchanged)
# =============================================================================

@bp.route('/xero/connect')
@login_required
def xero_connect():
    """Initiate Xero OAuth flow"""
    from app.integrations.xero_service import XeroService
    
    xero = XeroService()
    
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    session['xero_oauth_state'] = state
    
    auth_url = xero.get_auth_url(state=state)
    return redirect(auth_url)


@bp.route('/xero/callback')
@login_required
def xero_callback():
    """Handle Xero OAuth callback"""
    from app.integrations.xero_service import XeroService
    from app.models.xero import XeroConnection
    from app.extensions import db
    
    # Verify state
    state = request.args.get('state')
    if state != session.get('xero_oauth_state'):
        flash('Invalid OAuth state. Please try again.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Check for errors
    error = request.args.get('error')
    if error:
        flash(f'Xero authorization failed: {error}', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Get authorization code
    auth_code = request.args.get('code')
    
    if not auth_code:
        flash('Missing authorization code.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Exchange code for tokens
    xero = XeroService()
    tokens = xero.exchange_code_for_tokens(auth_code)
    
    if not tokens:
        flash('Failed to exchange authorization code for tokens.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Get connected organisations (tenants)
    connections = xero.get_connections(tokens['access_token'])
    
    if not connections:
        flash('No Xero organisations found. Please ensure you have access to at least one organisation.', 'error')
        return redirect(url_for('settings.settings_page'))
    
    # Use the first organisation (most users only have one)
    tenant = connections[0]
    
    # Check if connection already exists for this user
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection:
        # Update existing connection
        connection.tenant_id = tenant['tenantId']
        connection.tenant_name = tenant.get('tenantName', 'Unknown')
        connection.access_token = tokens['access_token']
        connection.refresh_token = tokens['refresh_token']
        connection.token_expires_at = datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 1800))
        connection.is_active = True
    else:
        # Create new connection
        connection = XeroConnection(
            user_id=current_user.id,
            tenant_id=tenant['tenantId'],
            tenant_name=tenant.get('tenantName', 'Unknown'),
            access_token=tokens['access_token'],
            refresh_token=tokens['refresh_token'],
            token_expires_at=datetime.utcnow() + timedelta(seconds=tokens.get('expires_in', 1800))
        )
        db.session.add(connection)
    
    db.session.commit()
    
    flash(f'Successfully connected to Xero: {connection.tenant_name}', 'success')
    
    # If user is in setup wizard, return there
    if not current_user.setup_completed:
        return redirect(url_for('setup.step', step=2))
    
    return redirect(url_for('integrations.xero_settings'))


@bp.route('/xero/disconnect', methods=['POST'])
@login_required
def xero_disconnect():
    """Disconnect Xero"""
    from app.models.xero import XeroConnection
    from app.extensions import db
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection:
        db.session.delete(connection)
        db.session.commit()
        flash('Xero disconnected successfully.', 'success')
    
    return redirect(url_for('integrations.xero_settings'))


@bp.route('/xero/settings')
@login_required
def xero_settings():
    """Xero settings page"""
    from app.models.xero import XeroConnection
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    expense_accounts = []
    sales_accounts = []
    
    if connection and connection.is_active:
        from app.integrations.xero_service import XeroService
        xero = XeroService(current_user)
        
        # Get accounts
        expense_accounts = xero.get_expense_accounts(connection)
        sales_accounts = xero.get_revenue_accounts(connection)
    
    return render_template('integrations/xero.html',
                         connection=connection,
                         expense_accounts=expense_accounts,
                         sales_accounts=sales_accounts)


@bp.route('/xero/settings/update', methods=['POST'])
@login_required
def xero_update_settings():
    """Update Xero settings"""
    from app.models.xero import XeroConnection
    from app.extensions import db
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    
    if not connection:
        return jsonify({'success': False, 'error': 'Not connected to Xero'}), 400
    
    # Update settings
    connection.default_expense_account_code = request.form.get('expense_account_code')
    connection.default_expense_account_name = request.form.get('expense_account_name')
    connection.default_sales_account_code = request.form.get('sales_account_code')
    connection.default_sales_account_name = request.form.get('sales_account_name')
    connection.auto_sync = request.form.get('auto_sync') == 'on'
    
    db.session.commit()
    
    flash('Xero settings updated.', 'success')
    return redirect(url_for('integrations.xero_settings'))


@bp.route('/xero/sync/<int:invoice_id>', methods=['POST'])
@login_required
def xero_sync_invoice(invoice_id):
    """Sync a single invoice to Xero as a Bill"""
    from app.models.invoice import Invoice
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get Xero connection
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'Xero not connected'}), 400
    
    if not connection.default_expense_account_code:
        return jsonify({'success': False, 'error': 'Please set a default expense account in Xero settings'}), 400
    
    # Sync to Xero
    xero = XeroService(current_user)
    result = xero.sync_invoice_to_bill(connection, invoice)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'message': f'Invoice synced to Xero as Bill #{result.get("bill_number", result.get("bill_id"))}'
        })
    else:
        return jsonify({'success': False, 'error': '; '.join(result.get('errors', ['Unknown error']))}), 400


@bp.route('/xero/sync-products/<int:invoice_id>', methods=['POST'])
@login_required
def xero_sync_products(invoice_id):
    """Sync invoice line items as Items in Xero"""
    from app.models.invoice import Invoice
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get Xero connection
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'Xero not connected'}), 400
    
    if not connection.default_expense_account_code or not connection.default_sales_account_code:
        return jsonify({'success': False, 'error': 'Please configure expense and sales accounts in Xero settings'}), 400
    
    # Sync products
    xero = XeroService(current_user)
    result = xero.sync_products_to_items(connection, invoice)
    
    return jsonify({
        'success': True,
        'message': f'Synced {result["synced"]} items, {result["failed"]} failed',
        'synced': result['synced'],
        'failed': result['failed'],
        'errors': result['errors']
    })


@bp.route('/api/xero/status')
@login_required
def xero_status():
    """Get Xero connection status"""
    from app.models.xero import XeroConnection
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    
    if connection and connection.is_active:
        return jsonify({
            'connected': True,
            'tenant_name': connection.tenant_name,
            'tenant_id': connection.tenant_id,
            'auto_sync': connection.auto_sync,
            'last_sync_at': connection.last_sync_at.isoformat() if connection.last_sync_at else None
        })
    
    return jsonify({'connected': False})


@bp.route('/api/xero/customers')
@login_required
def xero_customers():
    """Get all Xero customers"""
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'error': 'Xero not connected'}), 400
    
    xero = XeroService(current_user)
    customers = xero.get_customers(connection)
    
    return jsonify({
        'customers': [
            {
                'ContactID': c.get('ContactID'),
                'Name': c.get('Name'),
                'FirstName': c.get('FirstName'),
                'LastName': c.get('LastName'),
                'EmailAddress': c.get('EmailAddress')
            }
            for c in customers
        ]
    })

@bp.route('/api/xero/match-customer')
@login_required
def xero_match_customer():
    """Match job reference to Xero customer using Claude"""
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    
    job_reference = request.args.get('job_reference', '')
    
    if not job_reference:
        return jsonify({'matches': []})
    
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'error': 'Xero not connected'}), 400
    
    xero = XeroService(current_user)
    matches = xero.match_customer_to_job_reference(connection, job_reference)
    
    return jsonify({'matches': matches})

@bp.route('/xero/sync-to-customer/<int:invoice_id>', methods=['POST'])
@login_required
def xero_sync_to_customer(invoice_id):
    """Sync invoice to customer - creates items AND customer invoice in Xero"""
    from app.models.invoice import Invoice
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    from app.extensions import db
    
    data = request.get_json() or {}
    customer_id = data.get('customer_id')
    
    if not customer_id:
        return jsonify({'success': False, 'error': 'Customer ID required'}), 400
    
    # Get invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Get Xero connection
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'Xero not connected'}), 400
    
    if not connection.default_sales_account_code or not connection.default_expense_account_code:
        return jsonify({'success': False, 'error': 'Please configure expense and sales accounts in Xero settings'}), 400
    
    # Perform full sync
    xero = XeroService(current_user)
    result = xero.sync_to_customer_invoice(connection, invoice, customer_id)
    
    if result.get('success'):
        # Update invoice sync status
        invoice.xero_invoice_id = result.get('xero_invoice_id')
        invoice.xero_synced_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'products_synced': result.get('products_synced', 0),
            'products_failed': result.get('products_failed', 0),
            'invoice_action': result.get('invoice_action'),
            'xero_invoice_id': result.get('xero_invoice_id'),
            'xero_invoice_number': result.get('xero_invoice_number')
        })
    else:
        return jsonify({
            'success': False,
            'error': '; '.join(result.get('errors', ['Unknown error']))
        }), 400


@bp.route('/xero/create-quote/<int:quote_id>', methods=['POST'])
@login_required
def xero_create_quote(quote_id):
    """Create a Xero Quote from a GoZappify quote"""
    from app.models.invoice import Invoice
    from app.models.xero import XeroConnection
    from app.integrations.xero_service import XeroService
    
    data = request.get_json() or {}
    customer_id = data.get('customer_id')
    
    if not customer_id:
        return jsonify({'success': False, 'error': 'Customer ID required'}), 400
    
    # Get quote
    quote = Invoice.query.filter_by(id=quote_id, user_id=current_user.id, document_type='quote').first()
    if not quote:
        return jsonify({'success': False, 'error': 'Quote not found'}), 404
    
    # Get Xero connection
    connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    if not connection or not connection.is_active:
        return jsonify({'success': False, 'error': 'Xero not connected'}), 400
    
    if not connection.default_sales_account_code or not connection.default_expense_account_code:
        return jsonify({'success': False, 'error': 'Please configure expense and sales accounts in Xero settings'}), 400
    
    # Create quote in Xero
    xero = XeroService(current_user)
    result = xero.sync_quote_to_xero(connection, quote, customer_id)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'products_synced': result.get('products_synced', 0),
            'products_failed': result.get('products_failed', 0),
            'xero_quote_id': result.get('xero_quote_id'),
            'xero_quote_number': result.get('xero_quote_number')
        })
    else:
        return jsonify({
            'success': False,
            'error': '; '.join(result.get('errors', ['Unknown error']))
        }), 400
