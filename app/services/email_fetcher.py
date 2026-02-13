"""Email Fetcher Service - pulls PDF attachments from Gmail and IMAP into the invoice queue"""
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
from app.services.imap_fetcher import fetch_pdf_invoices_imap

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


def _save_pdf_to_queue(user_id, filename, file_data, sender, subject, email_date, msg_id, supplier_filters):
    """Save a PDF file to disk and create a queue entry. Returns 'fetched', 'skipped', or 'error'."""
    try:
        # Deduplication by message ID + filename
        if msg_id and QueuedInvoice.already_fetched(user_id, msg_id, filename):
            return 'skipped'
        
        file_hash = hashlib.sha256(file_data).hexdigest()
        
        # Deduplication by hash
        existing_hash = QueuedInvoice.query.filter_by(
            user_id=user_id,
            attachment_hash=file_hash
        ).first()
        
        if existing_hash:
            return 'skipped'
        
        # Save file
        upload_dir = os.path.join('uploads', 'queue', str(user_id))
        os.makedirs(upload_dir, exist_ok=True)
        
        safe_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{filename}"
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
        
        # Match supplier name
        supplier_name = _get_supplier_name(sender or '', supplier_filters) if supplier_filters else None
        
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
        return 'fetched'
    
    except Exception as e:
        logger.error(f"Failed to save PDF {filename}: {e}")
        return 'error'


def _fetch_gmail_for_user(user_id):
    """Fetch PDF invoices via Gmail API for a user and queue them"""
    result = {'fetched': 0, 'skipped': 0, 'errors': []}
    
    connection = EmailConnection.query.filter_by(
        user_id=user_id,
        provider='gmail',
        is_active=True
    ).first()
    
    if not connection:
        return result
    
    # Get supplier filters
    supplier_filters = SupplierFilter.query.filter_by(user_id=user_id).all()
    
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
    
    # Time filter
    if connection.last_checked:
        import calendar
        epoch = int(calendar.timegm(connection.last_checked.timetuple()))
        query += f" after:{epoch}"
    else:
        query += " newer_than:1d"
    
    logger.info(f"Gmail fetch for user {user_id} with query: {query}")
    
    try:
        service = _get_gmail_service(connection)
        
        messages_response = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=50
        ).execute()
        
        messages = messages_response.get('messages', [])
        logger.info(f"Found {len(messages)} matching Gmail emails for user {user_id}")
        
        for msg_stub in messages:
            msg_id = msg_stub['id']
            
            message = service.users().messages().get(
                userId='me',
                id=msg_id,
                format='full'
            ).execute()
            
            sender = _extract_sender(message)
            subject = _extract_subject(message)
            email_date = _extract_date(message)
            
            pdf_attachments = _find_pdf_attachments(message)
            
            if not pdf_attachments:
                continue
            
            for filename, attachment_id in pdf_attachments:
                try:
                    attachment = service.users().messages().attachments().get(
                        userId='me',
                        messageId=msg_id,
                        id=attachment_id
                    ).execute()
                    
                    file_data = base64.urlsafe_b64decode(attachment['data'])
                    
                    status = _save_pdf_to_queue(
                        user_id, filename, file_data, sender, subject,
                        email_date, msg_id, supplier_filters
                    )
                    
                    if status == 'fetched':
                        result['fetched'] += 1
                        logger.info(f"Queued Gmail PDF: {filename} from {sender} for user {user_id}")
                    elif status == 'skipped':
                        result['skipped'] += 1
                    else:
                        result['errors'].append(f"Failed to save {filename}")
                    
                except Exception as e:
                    error_msg = f"Failed to download {filename}: {str(e)}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
        
        # Update connection status
        connection.last_checked = datetime.utcnow()
        connection.last_error = None if not result['errors'] else '; '.join(result['errors'][:3])
        connection.emails_fetched_count = (connection.emails_fetched_count or 0) + result['fetched']
        db.session.commit()
        
    except Exception as e:
        error_msg = f"Gmail API error: {str(e)}"
        logger.error(f"Gmail fetch failed for user {user_id}: {error_msg}")
        result['errors'].append(error_msg)
        connection.last_checked = datetime.utcnow()
        connection.last_error = error_msg
        db.session.commit()
    
    return result


def _fetch_imap_for_user(user_id):
    """Fetch PDF invoices via IMAP for a user and queue them"""
    result = {'fetched': 0, 'skipped': 0, 'errors': []}
    
    connections = EmailConnection.query.filter_by(
        user_id=user_id,
        provider='imap',
        is_active=True
    ).all()
    
    if not connections:
        return result
    
    # Get supplier filters
    supplier_filters = SupplierFilter.query.filter_by(user_id=user_id).all()
    supplier_emails = [f.email_address for f in supplier_filters if f.is_active] if supplier_filters else None
    
    for connection in connections:
        try:
            token = connection.get_token()
            if not token:
                result['errors'].append(f'No credentials for {connection.email_address}')
                continue
            
            since_date = connection.last_checked or (datetime.utcnow() - timedelta(days=1))
            
            logger.info(f"IMAP fetch for user {user_id} from {connection.email_address} since {since_date}")
            
            pdfs = fetch_pdf_invoices_imap(
                server=token['server'],
                port=token['port'],
                email_address=token['email'],
                password=token['password'],
                since_date=since_date,
                supplier_emails=supplier_emails,
                use_ssl=token.get('use_ssl', True)
            )
            
            for pdf in pdfs:
                filename = pdf['filename']
                file_data = pdf['data']
                msg_id = pdf.get('message_id', '')
                sender = pdf.get('from', '')
                subject = pdf.get('subject', '')
                
                status = _save_pdf_to_queue(
                    user_id, filename, file_data, sender, subject,
                    None, msg_id, supplier_filters
                )
                
                if status == 'fetched':
                    result['fetched'] += 1
                    logger.info(f"Queued IMAP PDF: {filename} from {sender} for user {user_id}")
                elif status == 'skipped':
                    result['skipped'] += 1
                else:
                    result['errors'].append(f"Failed to save {filename}")
            
            # Update connection status
            connection.last_checked = datetime.utcnow()
            connection.last_error = None if not result['errors'] else '; '.join(result['errors'][:3])
            connection.emails_fetched_count = (connection.emails_fetched_count or 0) + result['fetched']
            db.session.commit()
            
        except Exception as e:
            error_msg = f"IMAP error ({connection.email_address}): {str(e)}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            connection.last_checked = datetime.utcnow()
            connection.last_error = error_msg
            db.session.commit()
    
    return result


def fetch_emails_for_user(user_id):
    """Fetch new invoice emails for a specific user and queue the PDFs.
    Checks both Gmail (OAuth) and IMAP connections.
    
    Returns dict with: fetched, skipped, errors
    """
    result = {'fetched': 0, 'skipped': 0, 'errors': []}
    
    # Fetch from Gmail
    gmail_result = _fetch_gmail_for_user(user_id)
    result['fetched'] += gmail_result['fetched']
    result['skipped'] += gmail_result['skipped']
    result['errors'].extend(gmail_result['errors'])
    
    # Fetch from IMAP
    imap_result = _fetch_imap_for_user(user_id)
    result['fetched'] += imap_result['fetched']
    result['skipped'] += imap_result['skipped']
    result['errors'].extend(imap_result['errors'])
    
    logger.info(f"Fetch complete for user {user_id}: {result['fetched']} fetched, {result['skipped']} skipped")
    
    return result


def fetch_all_users():
    """Fetch emails for all users with active email connections (Gmail + IMAP).
    Called by scheduled task / cron.
    """
    connections = EmailConnection.query.filter(
        EmailConnection.is_active == True
    ).all()
    
    # Get unique user IDs
    user_ids = list(set(conn.user_id for conn in connections))
    
    logger.info(f"Running email fetch for {len(user_ids)} users with {len(connections)} active connections")
    
    results = {}
    for uid in user_ids:
        try:
            results[uid] = fetch_emails_for_user(uid)
        except Exception as e:
            logger.error(f"Fetch failed for user {uid}: {e}")
            results[uid] = {'fetched': 0, 'skipped': 0, 'errors': [str(e)]}
    
    return results
