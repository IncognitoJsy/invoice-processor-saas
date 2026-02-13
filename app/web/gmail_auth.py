"""Gmail OAuth routes - connect/disconnect Gmail for auto-fetching invoices"""
from flask import Blueprint, redirect, request, jsonify, url_for, session, current_app
from flask_login import login_required, current_user
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
import json
import logging

from app.extensions import db
from app.models.email_connection import EmailConnection, SupplierFilter

logger = logging.getLogger(__name__)

bp = Blueprint('gmail_auth', __name__, url_prefix='/auth/gmail')

# Read-only scope - we only need to read emails, not modify them
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def _get_client_config():
    """Get Google OAuth client config from environment variables"""
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    
    if not client_id or not client_secret:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")
    
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.environ.get('GOOGLE_REDIRECT_URI', 'https://gozappify.com/auth/gmail/callback')]
        }
    }


def _get_redirect_uri():
    """Get the redirect URI"""
    return os.environ.get('GOOGLE_REDIRECT_URI', 'https://gozappify.com/auth/gmail/callback')


@bp.route('/connect')
@login_required
def connect():
    """Start Gmail OAuth flow - redirect user to Google consent screen"""
    try:
        client_config = _get_client_config()
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=_get_redirect_uri()
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',      # Get refresh token
            include_granted_scopes='true',
            prompt='consent'            # Always show consent to get refresh token
        )
        
        # Store state in session for CSRF protection
        session['gmail_oauth_state'] = state
        
        logger.info(f"User {current_user.id} starting Gmail OAuth flow")
        return redirect(authorization_url)
        
    except ValueError as e:
        logger.error(f"Gmail OAuth config error: {e}")
        return redirect('/queue/?error=gmail_not_configured')
    except Exception as e:
        logger.error(f"Gmail OAuth start error: {e}")
        return redirect('/queue/?error=gmail_connect_failed')


@bp.route('/callback')
@login_required
def callback():
    """Handle Google OAuth callback - exchange code for tokens"""
    try:
        # Verify state for CSRF protection
        stored_state = session.pop('gmail_oauth_state', None)
        if not stored_state:
            logger.warning("No OAuth state in session")
            return redirect('/queue/?error=invalid_state')
        
        client_config = _get_client_config()
        
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            redirect_uri=_get_redirect_uri(),
            state=stored_state
        )
        
        # Exchange authorization code for tokens
        flow.fetch_token(authorization_response=request.url)
        
        credentials = flow.credentials
        
        # Get the user's email address from Gmail API
        service = build('gmail', 'v1', credentials=credentials)
        profile = service.users().getProfile(userId='me').execute()
        email_address = profile.get('emailAddress', '')
        
        # Serialize credentials for storage
        token_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': list(credentials.scopes) if credentials.scopes else SCOPES
        }
        
        # Check if user already has a Gmail connection
        existing = EmailConnection.query.filter_by(
            user_id=current_user.id,
            provider='gmail'
        ).first()
        
        if existing:
            # Update existing connection
            existing.email_address = email_address
            existing.set_token(token_data)
            existing.is_active = True
            existing.last_error = None
            logger.info(f"Updated Gmail connection for user {current_user.id}: {email_address}")
        else:
            # Create new connection
            connection = EmailConnection(
                user_id=current_user.id,
                provider='gmail',
                email_address=email_address,
                is_active=True
            )
            connection.set_token(token_data)
            db.session.add(connection)
            logger.info(f"Created Gmail connection for user {current_user.id}: {email_address}")
        
        db.session.commit()
        return redirect('/queue/?success=gmail_connected')
        
    except Exception as e:
        logger.error(f"Gmail OAuth callback error: {e}")
        db.session.rollback()
        return redirect('/queue/?error=gmail_callback_failed')


@bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """Disconnect Gmail - remove OAuth tokens"""
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        provider='gmail'
    ).first()
    
    if connection:
        db.session.delete(connection)
        db.session.commit()
        logger.info(f"User {current_user.id} disconnected Gmail")
    
    return jsonify({'success': True, 'message': 'Gmail disconnected'})


@bp.route('/status')
@login_required
def status():
    """Get Gmail connection status"""
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        provider='gmail'
    ).first()
    
    if not connection:
        return jsonify({
            'connected': False
        })
    
    return jsonify({
        'connected': True,
        'email_address': connection.email_address,
        'is_active': connection.is_active,
        'last_checked': connection.last_checked.isoformat() if connection.last_checked else None,
        'last_error': connection.last_error,
        'emails_fetched_count': connection.emails_fetched_count
    })


@bp.route('/toggle', methods=['POST'])
@login_required
def toggle():
    """Toggle auto-fetch on/off"""
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        provider='gmail'
    ).first()
    
    if not connection:
        return jsonify({'success': False, 'error': 'Gmail not connected'}), 400
    
    connection.is_active = not connection.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_active': connection.is_active
    })


# === Supplier Filter API ===

@bp.route('/suppliers', methods=['GET'])
@login_required
def list_suppliers():
    """List user's supplier email filters"""
    filters = SupplierFilter.query.filter_by(user_id=current_user.id).all()
    return jsonify({
        'success': True,
        'suppliers': [f.to_dict() for f in filters]
    })


@bp.route('/suppliers', methods=['POST'])
@login_required
def add_supplier():
    """Add a supplier email filter"""
    data = request.get_json()
    
    if not data or not data.get('supplier_name') or not data.get('email_address'):
        return jsonify({'success': False, 'error': 'Supplier name and email required'}), 400
    
    # Check for duplicate
    existing = SupplierFilter.query.filter_by(
        user_id=current_user.id,
        email_address=data['email_address'].strip().lower()
    ).first()
    
    if existing:
        return jsonify({'success': False, 'error': 'This email is already in your supplier list'}), 400
    
    supplier = SupplierFilter(
        user_id=current_user.id,
        supplier_name=data['supplier_name'].strip(),
        email_address=data['email_address'].strip().lower(),
        is_active=True
    )
    db.session.add(supplier)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'supplier': supplier.to_dict()
    })


@bp.route('/suppliers/<int:supplier_id>', methods=['DELETE'])
@login_required
def delete_supplier(supplier_id):
    """Remove a supplier email filter"""
    supplier = SupplierFilter.query.filter_by(
        id=supplier_id,
        user_id=current_user.id
    ).first()
    
    if not supplier:
        return jsonify({'success': False, 'error': 'Supplier not found'}), 404
    
    db.session.delete(supplier)
    db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/suppliers/<int:supplier_id>/toggle', methods=['POST'])
@login_required
def toggle_supplier(supplier_id):
    """Toggle a supplier filter on/off"""
    supplier = SupplierFilter.query.filter_by(
        id=supplier_id,
        user_id=current_user.id
    ).first()
    
    if not supplier:
        return jsonify({'success': False, 'error': 'Supplier not found'}), 404
    
    supplier.is_active = not supplier.is_active
    db.session.commit()
    
    return jsonify({
        'success': True,
        'is_active': supplier.is_active
    })


@bp.route('/fetch-now', methods=['POST'])
@login_required
def fetch_now():
    """Manually trigger email fetch for current user (Gmail + IMAP)"""
    from app.services.email_fetcher import fetch_emails_for_user
    
    # Check if user has ANY active email connection
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).first()
    
    if not connection:
        return jsonify({'success': False, 'error': 'No email connected or inactive'}), 400
    
    try:
        result = fetch_emails_for_user(current_user.id)
        return jsonify({
            'success': True,
            'fetched': result.get('fetched', 0),
            'skipped': result.get('skipped', 0),
            'errors': result.get('errors', [])
        })
    except Exception as e:
        logger.error(f"Manual fetch failed for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
