"""Email Fetcher Service - pulls PDF attachments from Gmail into the invoice queue"""
import os
import base64
import hashlib
import logging
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.extensions import db
from app.models.email_connection import EmailConnection, SupplierFilter
from app.models.queued_invoice import QueuedInvoice

logger = logging.getLogger(__name__)


def _get_gmail_service(connection):
    """Build Gmail API service from stored encrypted credentials"""
    token_data = connection.get_token()
    if not token_data:
        raise ValueError("No token data found for connection")
    
    credentials = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
        scopes=token_data.get('scopes', ['https://www.googleapis.com/auth/gmail.readonly'])
    )
    
    # Refresh if expired
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        # Update stored token with new access token
        token_data['token'] = credentials.token
        connection.set_token(token_data)
        db.session.commit()
    
    return build('gmail', 'v1', credentials=credentials)


def _build_search_query(supplier_filters):
    """Build Gmail search query from supplier email filters
    
    Example: from:(invoices@wholesale.je OR accounts@yesss.co.uk) has:attachment filename:pdf
    """
    active_filters = [f for f in supplier_filters if f.is_active]
    
    if not active_filters:
        return None
    
    emails = [f.email_address for f in active_filters]
    
    if len(emails) == 1:
        from_clause = f"from:{emails[0]}"
    else:
        from_clause = "from:(" + " OR ".join(emails) + ")"
    
    return f"{from_clause} has:attachment filename:pdf"


def _get_supplier_name(from_email, supplier_filters):
    """Match email sender to supplier name"""
    for f in supplier_filters:
        if f.email_address.lower() in from_email.lower():
            return f.supplier_name
    return None


def _extract_sender(message):
    """Extract sender email from message headers"""
    headers = message.get('payload', {}).get('headers', [])
    for header in headers:
        if header['name'].lower() == 'from':
            value = header['value']
            # Extract email from "Name <email@example.com>" format
            if '<' in value:
                return value.split('<')[1].rstrip('>')
            return value
    return None


def _extract_subject(message):
    """Extract subject from message headers"""
    headers = message.get('payload', {}).get('headers', [])
    for header in headers:
        if header['name'].lower() == 'subject':
            return header['value']
    return None


def _extract_date(message):
    """Extract internal date from message"""
    internal_date = message.get('internalDate')
    if internal_date:
        return datetime.fromtimestamp(int(internal_date) / 1000)
    return None


def _find_pdf_attachments(message):
    """Find all PDF attachments in a message, returns list of (filename, attachment_id, part)"""
    attachments = []
    
    def _walk_parts(parts):
        for part in parts:
            mime_type = part.get('mimeType', '')
            filename = part.get('filename', '')
            
            if mime_type == 'application/pdf' or (filename and filename.lower().endswith('.pdf')):
                body = part.get('body', {})
                attachment_id = body.get('attachmentId')
                if attachment_id and filename:
                    attachments.append((filename, attachment_id))
            
            # Recurse into nested parts
            nested = part.get('parts', [])
            if nested:
                _walk_parts(nested)
    
    payload = message.get('payload', {})
    parts = payload.get('parts', [])
    
    if parts:
        _walk_parts(parts)
    else:
        # Single-part message
        mime_type = payload.get('mimeType', '')
        filename = payload.get('filename', '')
        body = payload.get('body', {})
        attachment_id = body.get('attachmentId')
        if (mime_type == 'application/pdf' or filename.lower().endswith('.pdf')) and attachment_id:
            attachments.append((filename, attachment_id))
    
    return attachments


def fetch_emails_for_user(user_id):
    """Fetch new invoice emails for a specific user and queue the PDFs
    
    Returns dict with: fetched, skipped, errors
    """
    from flask import current_app
    
    result = {'fetched': 0, 'skipped': 0, 'errors': []}
    
    # Get user's Gmail connection
    connection = EmailConnection.query.filter_by(
        user_id=user_id,
        provider='gmail',
        is_active=True
    ).first()
    
    if not connection:
        result['errors'].append('No active Gmail connection')
        return result
    
    # Get supplier filters
    supplier_filters = SupplierFilter.query.filter_by(
        user_id=user_id
    ).all()
    
    if not supplier_filters:
        result['errors'].append('No supplier email filters configured')
        connection.last_checked = datetime.utcnow()
        connection.last_error = 'No supplier filters'
        db.session.commit()
        return result
    
    # Build search query
    query = _build_search_query(supplier_filters)
    if not query:
        result['errors'].append('No active supplier filters')
        return result
    
    # Add time filter - only fetch emails from last 30 days
    # (on first run this gets recent history; subsequent runs are deduped)
    query += " newer_than:30d"
    
    logger.info(f"Fetching emails for user {user_id} with query: {query}")
    
    try:
        service = _get_gmail_service(connection)
        
        # Search for matching messages
        messages_response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=50  # Process up to 50 emails per fetch
        ).execute()
        
        messages = messages_response.get('messages', [])
        logger.info(f"Found {len(messages)} matching emails for user {user_id}")
        
        for msg_stub in messages:
            msg_id = msg_stub['id']
            
            # Get full message
            message = service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()
            
            sender = _extract_sender(message)
            subject = _extract_subject(message)
            email_date = _extract_date(message)
            supplier_name = _get_supplier_name(sender or '', supplier_filters)
            
            # Find PDF attachments
            pdf_attachments = _find_pdf_attachments(message)
            
            if not pdf_attachments:
                continue
            
            for filename, attachment_id in pdf_attachments:
                # Check deduplication
                if QueuedInvoice.already_fetched(user_id, msg_id, filename):
                    result['skipped'] += 1
                    continue
                
                try:
                    # Download attachment
                    attachment = service.users().messages().attachments().get(
                        userId='me',
                        messageId=msg_id,
                        id=attachment_id
                    ).execute()
                    
                    file_data = base64.urlsafe_b64decode(attachment['data'])
                    file_hash = hashlib.sha256(file_data).hexdigest()
                    
                    # Check hash dedup too
                    existing_hash = QueuedInvoice.query.filter_by(
                        user_id=user_id,
                        attachment_hash=file_hash
                    ).first()
                    
                    if existing_hash:
                        result['skipped'] += 1
                        continue
                    
                    # Save file
                    upload_dir = os.path.join('uploads', 'queue', str(user_id))
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    safe_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    # Clean filename
                    safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in '._-')
                    filepath = os.path.join(upload_dir, safe_filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(file_data)
                    
                    # Get page count
                    page_count = 1
                    try:
                        import fitz  # PyMuPDF
                        doc = fitz.open(filepath)
                        page_count = len(doc)
                        doc.close()
                    except Exception:
                        pass
                    
                    # Create queue entry
                    queued = QueuedInvoice(
                        user_id=user_id,
                        filename=safe_filename,
                        original_filename=filename,
                        file_path=filepath,
                        file_size=len(file_data),
                        page_count=page_count,
                        source='email',
                        source_email=sender,
                        supplier_name=supplier_name,
                        email_subject=subject,
                        email_received_date=email_date,
                        email_message_id=msg_id,
                        attachment_hash=file_hash,
                        status='queued'
                    )
                    db.session.add(queued)
                    result['fetched'] += 1
                    
                    logger.info(f"Queued PDF: {filename} from {sender} for user {user_id}")
                    
                except Exception as e:
                    error_msg = f"Failed to download {filename}: {str(e)}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
        
        # Update connection status
        connection.last_checked = datetime.utcnow()
        connection.last_error = None if not result['errors'] else '; '.join(result['errors'][:3])
        connection.emails_fetched_count = (connection.emails_fetched_count or 0) + result['fetched']
        db.session.commit()
        
        logger.info(f"Fetch complete for user {user_id}: {result['fetched']} fetched, {result['skipped']} skipped")
        
    except Exception as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(f"Fetch failed for user {user_id}: {error_msg}")
        result['errors'].append(error_msg)
        
        connection.last_checked = datetime.utcnow()
        connection.last_error = error_msg
        db.session.commit()
    
    return result


def fetch_all_users():
    """Fetch emails for all users with active Gmail connections.
    Called by scheduled task / cron.
    """
    connections = EmailConnection.query.filter_by(
        provider='gmail',
        is_active=True
    ).all()
    
    logger.info(f"Running email fetch for {len(connections)} active connections")
    
    results = {}
    for conn in connections:
        try:
            results[conn.user_id] = fetch_emails_for_user(conn.user_id)
        except Exception as e:
            logger.error(f"Fetch failed for user {conn.user_id}: {e}")
            results[conn.user_id] = {'fetched': 0, 'skipped': 0, 'errors': [str(e)]}
    
    return results
