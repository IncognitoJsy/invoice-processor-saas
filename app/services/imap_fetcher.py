"""
IMAP Email Fetcher Service for GoZappify
=========================================
Handles IMAP connections for non-Gmail email providers.
Works alongside the existing Gmail OAuth integration.

Add this file to: app/services/imap_fetcher.py
"""
import imaplib
import email
from email.header import decode_header
import os
import logging
import tempfile
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


# Common IMAP server settings for auto-detection
IMAP_SERVERS = {
    # Microsoft
    'outlook.com': ('outlook.office365.com', 993),
    'hotmail.com': ('outlook.office365.com', 993),
    'live.com': ('outlook.office365.com', 993),
    'msn.com': ('outlook.office365.com', 993),
    'office365.com': ('outlook.office365.com', 993),
    
    # Yahoo
    'yahoo.com': ('imap.mail.yahoo.com', 993),
    'yahoo.co.uk': ('imap.mail.yahoo.com', 993),
    
    # Apple
    'icloud.com': ('imap.mail.me.com', 993),
    'me.com': ('imap.mail.me.com', 993),
    'mac.com': ('imap.mail.me.com', 993),
    
    # AOL
    'aol.com': ('imap.aol.com', 993),
    
    # Zoho
    'zoho.com': ('imap.zoho.com', 993),
    
    # BT / Sky / Virgin (UK ISPs - common for tradespeople)
    'btinternet.com': ('mail.btinternet.com', 993),
    'btopenworld.com': ('mail.btinternet.com', 993),
    'sky.com': ('imap.tools.sky.com', 993),
    'virginmedia.com': ('imap.virginmedia.com', 993),
    
    # Jersey / Channel Islands
    'jerseymail.co.uk': ('mail.jerseymail.co.uk', 993),
    
    # Common business email
    'ionos.co.uk': ('imap.ionos.co.uk', 993),
    '1and1.co.uk': ('imap.ionos.co.uk', 993),
    'godaddy.com': ('imap.secureserver.net', 993),
    '123-reg.co.uk': ('imap.123-reg.co.uk', 993),
}


def guess_imap_server(email_address):
    """
    Try to auto-detect IMAP server from email domain.
    Returns (server, port) or (None, None) if unknown.
    """
    domain = email_address.split('@')[-1].lower()
    
    # Direct match
    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]
    
    # Try common patterns for custom domains
    # Most business email is hosted on one of the big platforms
    return None, None


def test_imap_connection(server, port, email_address, password, use_ssl=True):
    """
    Test an IMAP connection. Returns (success, error_message).
    Use this before saving credentials to verify they work.
    """
    try:
        if use_ssl:
            mail = imaplib.IMAP4_SSL(server, port, timeout=15)
        else:
            mail = imaplib.IMAP4(server, port, timeout=15)
        
        mail.login(email_address, password)
        
        # Try to select inbox to verify full access
        status, _ = mail.select('INBOX', readonly=True)
        if status != 'OK':
            mail.logout()
            return False, "Connected but could not access inbox"
        
        mail.logout()
        return True, "Connection successful"
        
    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        if 'AUTHENTICATIONFAILED' in error_msg.upper() or 'LOGIN' in error_msg.upper():
            return False, "Invalid email or password. If using Gmail/Outlook, you may need an App Password."
        elif 'PRIVACYREQUIRED' in error_msg.upper():
            return False, "Server requires a more secure connection. Try enabling SSL."
        return False, f"Authentication error: {error_msg}"
    except ConnectionRefusedError:
        return False, f"Could not connect to {server}:{port}. Check server address and port."
    except TimeoutError:
        return False, f"Connection timed out. Check server address: {server}"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"


def fetch_pdf_invoices_imap(server, port, email_address, password, 
                             since_date=None, supplier_emails=None, 
                             use_ssl=True, max_results=50):
    """
    Fetch PDF attachments from an IMAP mailbox.
    
    Args:
        server: IMAP server hostname
        port: IMAP port (usually 993 for SSL)
        email_address: Login email
        password: Login password or app password
        since_date: Only fetch emails after this datetime
        supplier_emails: List of supplier email addresses to filter by (optional)
        use_ssl: Use SSL/TLS connection
        max_results: Maximum number of emails to process
    
    Returns:
        List of dicts: [{"filename": str, "data": bytes, "from": str, 
                         "subject": str, "date": str, "message_id": str}]
    """
    results = []
    mail = None
    
    try:
        # Connect
        if use_ssl:
            mail = imaplib.IMAP4_SSL(server, port, timeout=30)
        else:
            mail = imaplib.IMAP4(server, port, timeout=30)
        
        mail.login(email_address, password)
        mail.select('INBOX', readonly=True)
        
        # Build search criteria
        search_parts = []
        
        if since_date:
            # IMAP date format: DD-Mon-YYYY
            date_str = since_date.strftime('%d-%b-%Y')
            search_parts.append(f'SINCE {date_str}')
        
        # Search for emails with attachments (not all servers support HEADER search)
        # We'll filter for PDFs after fetching
        if supplier_emails and len(supplier_emails) > 0:
            # Search for emails from any of the supplier addresses
            if len(supplier_emails) == 1:
                search_parts.append(f'FROM "{supplier_emails[0]}"')
            else:
                # IMAP OR syntax is nested: (OR (FROM "a") (FROM "b"))
                # For simplicity, we'll do separate searches and combine
                pass  # Handle below
        
        # If we have multiple suppliers, do separate searches
        if supplier_emails and len(supplier_emails) > 1:
            all_message_ids = set()
            for sup_email in supplier_emails:
                criteria = ' '.join(search_parts + [f'FROM "{sup_email}"'])
                if not criteria:
                    criteria = 'ALL'
                status, data = mail.search(None, f'({criteria})')
                if status == 'OK' and data[0]:
                    ids = data[0].split()
                    all_message_ids.update(ids)
            message_ids = sorted(all_message_ids, key=lambda x: int(x))[-max_results:]
        else:
            criteria = ' '.join(search_parts) if search_parts else 'ALL'
            status, data = mail.search(None, f'({criteria})')
            if status != 'OK' or not data[0]:
                logger.info(f"No emails found matching criteria: {criteria}")
                return results
            message_ids = data[0].split()[-max_results:]
        
        logger.info(f"Found {len(message_ids)} emails to check for PDFs")
        
        # Process each email
        for msg_id in message_ids:
            try:
                status, msg_data = mail.fetch(msg_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Get message metadata
                from_addr = msg.get('From', '')
                subject = ''
                raw_subject = msg.get('Subject', '')
                if raw_subject:
                    decoded_parts = decode_header(raw_subject)
                    subject = ''.join(
                        part.decode(charset or 'utf-8') if isinstance(part, bytes) else part
                        for part, charset in decoded_parts
                    )
                
                date_str = msg.get('Date', '')
                message_id = msg.get('Message-ID', str(msg_id))
                
                # Walk through parts looking for PDF attachments
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get('Content-Disposition', ''))
                    
                    if 'attachment' in content_disposition or content_type == 'application/pdf':
                        filename = part.get_filename()
                        
                        if filename:
                            # Decode filename if needed
                            decoded_parts = decode_header(filename)
                            filename = ''.join(
                                p.decode(charset or 'utf-8') if isinstance(p, bytes) else p
                                for p, charset in decoded_parts
                            )
                        
                        # Check if it's a PDF
                        if filename and filename.lower().endswith('.pdf') or content_type == 'application/pdf':
                            if not filename:
                                filename = f"invoice_{msg_id.decode() if isinstance(msg_id, bytes) else msg_id}.pdf"
                            
                            pdf_data = part.get_payload(decode=True)
                            if pdf_data and len(pdf_data) > 100:  # Skip tiny/empty files
                                results.append({
                                    "filename": filename,
                                    "data": pdf_data,
                                    "from": from_addr,
                                    "subject": subject,
                                    "date": date_str,
                                    "message_id": message_id,
                                    "size": len(pdf_data),
                                })
                                logger.info(f"Found PDF: {filename} from {from_addr}")
            
            except Exception as e:
                logger.warning(f"Error processing email {msg_id}: {e}")
                continue
        
        return results
    
    except Exception as e:
        logger.error(f"IMAP fetch error: {e}")
        raise
    
    finally:
        if mail:
            try:
                mail.logout()
            except:
                pass
