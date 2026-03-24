"""Email sending service for GoZappify
Handles sending invoices via Gmail API (OAuth) or SMTP (IMAP users)
"""
import base64
import logging
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formataddr

logger = logging.getLogger(__name__)


def get_email_connection(user):
    """Get the user's active email connection"""
    from app.models.email_connection import EmailConnection
    return EmailConnection.query.filter_by(
        user_id=user.id,
        is_active=True
    ).first()


def send_invoice_email(user, invoice, pdf_bytes=None):
    """Send a customer invoice via the user's connected email.
    
    Returns: (success: bool, message: str)
    """
    connection = get_email_connection(user)
    
    if not connection:
        return False, "No email account connected. Please set up email in Settings."
    
    if not invoice.customer.email:
        return False, f"No email address for {invoice.customer.display_name}."
    
    # Build email content
    subject = f"Invoice {invoice.invoice_number} from {user.company_name or 'GoZappify'}"
    
    html_body = _build_invoice_email_html(user, invoice)
    text_body = _build_invoice_email_text(user, invoice)
    
    if connection.provider == 'gmail':
        return _send_via_gmail(connection, user, invoice, subject, html_body, text_body, pdf_bytes)
    else:
        return _send_via_smtp(connection, user, invoice, subject, html_body, text_body, pdf_bytes)


def _build_invoice_email_html(user, invoice):
    """Build HTML email body"""
    company = user.company_name or 'Your Contractor'
    due_date = invoice.due_date.strftime('%d %b %Y') if invoice.due_date else 'Upon receipt'
    
    bank_section = ''
    if user.bank_account_number or user.bank_iban:
        bank_rows = ''
        if user.bank_name:
            bank_rows += f'<tr><td style="color:#6b7280;padding:4px 0;">Bank:</td><td style="font-weight:600;padding:4px 0 4px 16px;">{user.bank_name}</td></tr>'
        if user.bank_account_name:
            bank_rows += f'<tr><td style="color:#6b7280;padding:4px 0;">Account Name:</td><td style="font-weight:600;padding:4px 0 4px 16px;">{user.bank_account_name}</td></tr>'
        if user.bank_account_number:
            bank_rows += f'<tr><td style="color:#6b7280;padding:4px 0;">Account No:</td><td style="font-weight:600;font-family:monospace;padding:4px 0 4px 16px;">{user.bank_account_number}</td></tr>'
        if user.bank_sort_code:
            bank_rows += f'<tr><td style="color:#6b7280;padding:4px 0;">Sort Code:</td><td style="font-weight:600;font-family:monospace;padding:4px 0 4px 16px;">{user.bank_sort_code}</td></tr>'
        if user.bank_iban:
            bank_rows += f'<tr><td style="color:#6b7280;padding:4px 0;">IBAN:</td><td style="font-weight:600;font-family:monospace;padding:4px 0 4px 16px;">{user.bank_iban}</td></tr>'
        
        bank_section = f'''
        <div style="background:#f9fafb;border-radius:8px;padding:20px;margin:24px 0;text-align:center;">
            <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;margin:0 0 12px 0;">Payment Details</p>
            <table style="margin:0 auto;border-collapse:collapse;">
                {bank_rows}
            </table>
            <p style="font-size:12px;color:#9ca3af;margin:12px 0 0 0;">
                Please use <strong style="color:#374151;">{invoice.invoice_number}</strong> as your payment reference
            </p>
        </div>'''

    lines_html = ''
    for line in invoice.lines:
        lines_html += f'''
        <tr>
            <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:14px;color:#374151;">{line.description}</td>
            <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:14px;color:#6b7280;text-align:right;">{line.quantity}</td>
            <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:14px;color:#6b7280;text-align:right;">£{line.unit_price:.2f}</td>
            <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:14px;font-weight:600;color:#111827;text-align:right;">£{line.line_total:.2f}</td>
        </tr>'''

    notes = invoice.notes or user.invoice_notes or ''
    notes_section = f'<p style="font-size:13px;color:#9ca3af;margin-top:24px;">{notes}</p>' if notes else ''

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f3f4f6;margin:0;padding:32px 16px;">
    <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.07);">
        
        <!-- Header -->
        <div style="background:#2563eb;padding:32px;color:white;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <h1 style="margin:0;font-size:22px;font-weight:800;">{company}</h1>
                    {f'<p style="margin:4px 0 0;font-size:13px;opacity:0.8;">{user.trade_type.title()}</p>' if user.trade_type else ''}
                </div>
                <div style="text-align:right;">
                    <p style="margin:0;font-size:28px;font-weight:900;font-family:monospace;">{invoice.invoice_number}</p>
                    <p style="margin:4px 0 0;font-size:12px;opacity:0.7;">INVOICE</p>
                </div>
            </div>
        </div>

        <div style="padding:32px;">
            <!-- Invoice details -->
            <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
                <tr>
                    <td style="vertical-align:top;width:50%;">
                        <p style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;margin:0 0 6px;">Bill To</p>
                        <p style="margin:0;font-size:16px;font-weight:700;color:#111827;">{invoice.customer.display_name}</p>
                        {f'<p style="margin:2px 0 0;font-size:13px;color:#6b7280;">{invoice.customer.email}</p>' if invoice.customer.email else ''}
                    </td>
                    <td style="vertical-align:top;text-align:right;">
                        <p style="margin:0 0 4px;font-size:13px;color:#6b7280;">Issue Date: <strong style="color:#374151;">{invoice.issue_date.strftime("%d %b %Y") if invoice.issue_date else "—"}</strong></p>
                        <p style="margin:0 0 4px;font-size:13px;color:#6b7280;">Due Date: <strong style="color:#374151;">{due_date}</strong></p>
                        <p style="margin:0;font-size:13px;color:#6b7280;">Terms: <strong style="color:#374151;">{invoice.payment_terms_label}</strong></p>
                    </td>
                </tr>
            </table>

            <!-- Line items -->
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="border-bottom:2px solid #111827;">
                        <th style="text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;padding:0 0 8px;">Description</th>
                        <th style="text-align:right;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;padding:0 0 8px;">Qty</th>
                        <th style="text-align:right;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;padding:0 0 8px;">Price</th>
                        <th style="text-align:right;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#9ca3af;padding:0 0 8px;">Total</th>
                    </tr>
                </thead>
                <tbody>{lines_html}</tbody>
            </table>

            <!-- Total -->
            <div style="text-align:right;margin-top:16px;padding-top:16px;border-top:2px solid #111827;">
                {f'<p style="margin:0 0 4px;font-size:13px;color:#6b7280;">Subtotal: £{invoice.subtotal:.2f}</p>' if invoice.tax_rate else ''}
                {f'<p style="margin:0 0 8px;font-size:13px;color:#6b7280;">{user.tax_type or "Tax"} ({invoice.tax_rate}%): £{invoice.tax_amount:.2f}</p>' if invoice.tax_rate else ''}
                <p style="margin:0;font-size:22px;font-weight:900;color:#111827;">Total Due: £{invoice.total:.2f}</p>
            </div>

            {bank_section}
            {notes_section}
        </div>
    </div>
    <p style="text-align:center;font-size:12px;color:#9ca3af;margin-top:24px;">
        Sent via GoZappify
    </p>
</body>
</html>'''


def _build_invoice_email_text(user, invoice):
    """Plain text fallback"""
    company = user.company_name or 'Your Contractor'
    lines = '\n'.join([f"  {l.description} x{l.quantity} @ £{l.unit_price:.2f} = £{l.line_total:.2f}" for l in invoice.lines])
    bank = ''
    if user.bank_account_number:
        bank = f"\nPayment Details:\n  Account: {user.bank_account_number}\n  Sort Code: {user.bank_sort_code or '—'}"
        if user.bank_iban:
            bank += f"\n  IBAN: {user.bank_iban}"
        bank += f"\n  Reference: {invoice.invoice_number}"
    
    return f"""Invoice {invoice.invoice_number} from {company}

Bill To: {invoice.customer.display_name}
Issue Date: {invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '—'}
Due Date: {invoice.due_date.strftime('%d %b %Y') if invoice.due_date else '—'}

Items:
{lines}

Total Due: £{invoice.total:.2f}
{bank}

Sent via GoZappify
"""


def _send_via_gmail(connection, user, invoice, subject, html_body, text_body, pdf_bytes):
    """Send via Gmail API using OAuth token"""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        token_data = connection.get_token()
        if not token_data:
            return False, "Gmail credentials not found. Please reconnect your email."

        credentials = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret'),
            scopes=token_data.get('scopes', [])
        )

        # Refresh if expired
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            # Save updated token
            token_data['token'] = credentials.token
            connection.set_token(token_data)
            from app.extensions import db
            db.session.commit()

        # Check we have send scope
        scopes = token_data.get('scopes', [])
        has_send_scope = any('send' in s for s in scopes)
        
        if not has_send_scope:
            return False, "Gmail send permission not granted. Please reconnect email with send permission."

        # Build message
        msg = _build_mime_message(
            from_addr=formataddr((user.company_name or 'GoZappify', connection.email_address)),
            to_addr=invoice.customer.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            pdf_bytes=pdf_bytes,
            invoice_number=invoice.invoice_number
        )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = build('gmail', 'v1', credentials=credentials)
        service.users().messages().send(userId='me', body={'raw': raw}).execute()

        return True, f"Invoice sent to {invoice.customer.email}"

    except Exception as e:
        logger.error(f"Gmail send error: {e}")
        return False, f"Failed to send via Gmail: {str(e)}"


def _send_via_smtp(connection, user, invoice, subject, html_body, text_body, pdf_bytes):
    """Send via SMTP using stored credentials"""
    try:
        token_data = connection.get_token()
        if not token_data:
            return False, "Email credentials not found. Please reconnect your email."

        password = token_data.get('password', '')
        smtp_server = connection.smtp_server or _guess_smtp_server(connection.imap_server)
        smtp_port = connection.smtp_port or 587
        use_tls = connection.smtp_use_tls if connection.smtp_use_tls is not None else True

        if not smtp_server:
            return False, "SMTP server not configured. Please update your email settings."

        msg = _build_mime_message(
            from_addr=formataddr((user.company_name or 'GoZappify', connection.email_address)),
            to_addr=invoice.customer.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            pdf_bytes=pdf_bytes,
            invoice_number=invoice.invoice_number
        )

        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            if use_tls:
                server.starttls()
            server.login(connection.email_address, password)
            server.sendmail(connection.email_address, invoice.customer.email, msg.as_string())

        return True, f"Invoice sent to {invoice.customer.email}"

    except smtplib.SMTPAuthenticationError:
        return False, "Email authentication failed. Please check your email password in Settings."
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False, f"Failed to send email: {str(e)}"
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False, f"Unexpected error sending email: {str(e)}"


def _build_mime_message(from_addr, to_addr, subject, html_body, text_body, pdf_bytes, invoice_number):
    """Build a MIME email message with optional PDF attachment"""
    msg = MIMEMultipart('mixed')
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Subject'] = subject

    # Attach text and HTML
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(text_body, 'plain'))
    alt.attach(MIMEText(html_body, 'html'))
    msg.attach(alt)

    # Attach PDF if provided
    if pdf_bytes:
        pdf_part = MIMEApplication(pdf_bytes, _subtype='pdf')
        pdf_part.add_header('Content-Disposition', 'attachment',
                           filename=f'{invoice_number}.pdf')
        msg.attach(pdf_part)

    return msg


def _guess_smtp_server(imap_server):
    """Guess SMTP server from IMAP server address"""
    if not imap_server:
        return None
    return imap_server.replace('imap.', 'smtp.').replace('imap', 'smtp')
