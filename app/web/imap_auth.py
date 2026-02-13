"""
IMAP Email Connection Routes for GoZappify
============================================
Handles connecting non-Gmail email accounts via IMAP.
Works alongside gmail_auth.py for Gmail OAuth connections.

Add this file to: app/web/imap_auth.py
"""
from flask import Blueprint, request, jsonify, redirect
from flask_login import login_required, current_user
from app.extensions import db
from app.models.email_connection import EmailConnection
from app.services.imap_fetcher import test_imap_connection, guess_imap_server
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('imap_auth', __name__, url_prefix='/auth/imap')


@bp.route('/connect', methods=['POST'])
@login_required
def connect():
    """
    Connect an IMAP email account.
    Expects JSON: {email, password, server (optional), port (optional)}
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    email_address = data.get('email', '').strip()
    password = data.get('password', '').strip()
    server = data.get('server', '').strip()
    port = data.get('port')
    use_ssl = data.get('use_ssl', True)
    
    if not email_address or not password:
        return jsonify({'success': False, 'error': 'Email and password are required'}), 400
    
    # Auto-detect server if not provided
    if not server:
        detected_server, detected_port = guess_imap_server(email_address)
        if detected_server:
            server = detected_server
            port = port or detected_port
            logger.info(f"Auto-detected IMAP server for {email_address}: {server}:{port}")
        else:
            return jsonify({
                'success': False, 
                'error': 'Could not auto-detect email server. Please enter your IMAP server address manually.',
                'need_manual': True
            }), 400
    
    port = int(port) if port else 993
    
    # Test the connection before saving
    success, message = test_imap_connection(server, port, email_address, password, use_ssl)
    
    if not success:
        logger.warning(f"IMAP connection test failed for {email_address}: {message}")
        return jsonify({
            'success': False, 
            'error': message,
            'help': _get_help_text(email_address)
        }), 400
    
    # Connection works — save it
    try:
        # Check for existing connection
        existing = EmailConnection.query.filter_by(
            user_id=current_user.id,
            provider='imap'
        ).first()
        
        # Also check if they already have a Gmail connection with this email
        gmail_existing = EmailConnection.query.filter_by(
            user_id=current_user.id,
            provider='gmail',
            email_address=email_address
        ).first()
        
        if gmail_existing:
            return jsonify({
                'success': False,
                'error': 'This email is already connected via Gmail. Disconnect Gmail first if you want to use IMAP instead.'
            }), 400
        
        # Store IMAP credentials (encrypted)
        token_data = {
            'server': server,
            'port': port,
            'email': email_address,
            'password': password,
            'use_ssl': use_ssl,
        }
        
        if existing:
            existing.email_address = email_address
            existing.set_token(token_data)
            existing.is_active = True
            existing.last_error = None
            existing.imap_server = server
            existing.imap_port = port
            logger.info(f"Updated IMAP connection for user {current_user.id}: {email_address}")
        else:
            connection = EmailConnection(
                user_id=current_user.id,
                provider='imap',
                email_address=email_address,
                is_active=True,
                imap_server=server,
                imap_port=port,
            )
            connection.set_token(token_data)
            db.session.add(connection)
            logger.info(f"Created IMAP connection for user {current_user.id}: {email_address}")
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Connected to {email_address} successfully!',
            'email': email_address,
            'server': server
        })
    
    except Exception as e:
        logger.error(f"Error saving IMAP connection: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Failed to save connection. Please try again.'}), 500


@bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """Disconnect IMAP email account"""
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        provider='imap'
    ).first()
    
    if connection:
        db.session.delete(connection)
        db.session.commit()
        logger.info(f"User {current_user.id} disconnected IMAP")
    
    return jsonify({'success': True, 'message': 'Email disconnected'})

@bp.route('/status')
@login_required
def status():
    """Get IMAP connection status"""
    connection = EmailConnection.query.filter_by(
        user_id=current_user.id,
        provider='imap'
    ).first()
    
    if not connection:
        return jsonify({'connected': False})
    
    return jsonify({
        'connected': True,
        'email_address': connection.email_address,
        'is_active': connection.is_active,
        'last_checked': connection.last_checked.isoformat() if connection.last_checked else None,
        'last_error': connection.last_error,
        'emails_fetched_count': connection.emails_fetched_count
    })    


@bp.route('/test', methods=['POST'])
@login_required
def test_connection():
    """Test IMAP connection without saving"""
    data = request.get_json()
    
    email_address = data.get('email', '').strip()
    password = data.get('password', '').strip()
    server = data.get('server', '').strip()
    port = data.get('port')
    use_ssl = data.get('use_ssl', True)
    
    if not email_address or not password:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400
    
    if not server:
        detected_server, detected_port = guess_imap_server(email_address)
        if detected_server:
            server = detected_server
            port = port or detected_port
        else:
            return jsonify({
                'success': False, 
                'error': 'Could not detect server. Please enter IMAP server manually.',
                'need_manual': True
            }), 400
    
    port = int(port) if port else 993
    success, message = test_imap_connection(server, port, email_address, password, use_ssl)
    
    return jsonify({
        'success': success, 
        'message': message,
        'server': server,
        'port': port
    })


@bp.route('/detect-server', methods=['POST'])
@login_required
def detect_server():
    """Auto-detect IMAP server from email address"""
    data = request.get_json()
    email_address = data.get('email', '').strip()
    
    if not email_address or '@' not in email_address:
        return jsonify({'success': False, 'error': 'Valid email required'}), 400
    
    server, port = guess_imap_server(email_address)
    
    if server:
        return jsonify({
            'success': True,
            'server': server,
            'port': port,
            'auto_detected': True
        })
    else:
        domain = email_address.split('@')[-1]
        return jsonify({
            'success': False,
            'error': f'Could not auto-detect server for {domain}. Please enter IMAP details manually.',
            'domain': domain,
            'suggestion': f'Try imap.{domain} on port 993'
        })


def _get_help_text(email_address):
    """Return provider-specific help text for connection issues"""
    domain = email_address.split('@')[-1].lower()
    
    if domain in ('gmail.com', 'googlemail.com'):
        return ("For Gmail, use the 'Connect Gmail' button instead — it uses a more secure "
                "connection. If you prefer IMAP, you'll need to create an App Password at "
                "https://myaccount.google.com/apppasswords")
    
    if domain in ('outlook.com', 'hotmail.com', 'live.com'):
        return ("For Outlook/Hotmail, you may need to create an App Password. "
                "Go to https://account.microsoft.com/security and look for 'App passwords'. "
                "You may also need to enable IMAP in your Outlook settings.")
    
    if domain in ('yahoo.com', 'yahoo.co.uk'):
        return ("Yahoo requires an App Password for third-party apps. "
                "Go to Yahoo Account Security → Generate app password.")
    
    if domain in ('icloud.com', 'me.com', 'mac.com'):
        return ("Apple iCloud requires an App-Specific Password. "
                "Go to https://appleid.apple.com → Security → App-Specific Passwords.")
    
    if domain in ('btinternet.com', 'btopenworld.com'):
        return ("BT email: Make sure IMAP is enabled in your BT Mail settings. "
                "Server: mail.btinternet.com, Port: 993, SSL: Yes")
    
    if domain in ('sky.com',):
        return ("Sky email: Server: imap.tools.sky.com, Port: 993, SSL: Yes. "
                "Use your Sky ID password.")
    
    return ("Check that IMAP access is enabled in your email settings. "
            "Some providers require an 'App Password' instead of your regular password. "
            "Contact your email provider if you're unsure.")
