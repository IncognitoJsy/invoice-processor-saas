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
    """Build clean customer-facing email with view link"""
    company = user.company_name or 'GoZappify'
    due_date = invoice.due_date.strftime('%d %b %Y') if invoice.due_date else 'On receipt'
    total = f"£{invoice.total:.2f}" if invoice.total else '£0.00'
    view_url = invoice.view_url or ''
    brand_colour = user.invoice_colour or '#2563eb'
    bank_details = ''
    if user.bank_name or user.bank_account_number or user.bank_sort_code:
        bank_details = f"""
        <div style="background:#f8fafc;border-radius:8px;padding:16px;margin-top:20px;">
            <p style="font-size:13px;color:#64748b;margin:0 0 8px;font-weight:600;">PAYMENT DETAILS</p>
            {'<p style="font-size:14px;color:#1e293b;margin:4px 0;">Bank: ' + user.bank_name + '</p>' if user.bank_name else ''}
            {'<p style="font-size:14px;color:#1e293b;margin:4px 0;">Account: ' + (user.bank_account_number or '') + '</p>' if user.bank_account_number else ''}
            {'<p style="font-size:14px;color:#1e293b;margin:4px 0;">Sort Code: ' + (user.bank_sort_code or '') + '</p>' if user.bank_sort_code else ''}
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 20px;">
    <tr><td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">

            <!-- Header -->
            <tr><td style="background:{brand_colour};border-radius:12px 12px 0 0;padding:28px 32px;">
                <h1 style="color:white;margin:0;font-size:22px;font-weight:700;">{company}</h1>
                <p style="color:rgba(255,255,255,0.85);margin:4px 0 0;font-size:14px;">Invoice {invoice.invoice_number}</p>
            </td></tr>

            <!-- Body -->
            <tr><td style="background:white;padding:32px;">
                <p style="color:#374151;font-size:15px;margin:0 0 8px;">Hi {invoice.customer.display_name},</p>
                <p style="color:#6b7280;font-size:14px;line-height:1.6;margin:0 0 24px;">
                    Please find your invoice from {company} for <strong style="color:#111827;">£{invoice.total:.2f}</strong>,
                    due on <strong style="color:#111827;">{due_date}</strong>.
                </p>

                <!-- Invoice summary box -->
                <div style="background:#f8fafc;border-radius:8px;padding:20px;margin-bottom:24px;">
                    <table width="100%" cellpadding="0" cellspacing="0">
                        <tr>
                            <td style="font-size:13px;color:#6b7280;">Invoice Number</td>
                            <td style="font-size:13px;color:#111827;text-align:right;font-weight:600;">{invoice.invoice_number}</td>
                        </tr>
                        <tr><td colspan="2" style="padding:4px 0;"></td></tr>
                        <tr>
                            <td style="font-size:13px;color:#6b7280;">Due Date</td>
                            <td style="font-size:13px;color:#111827;text-align:right;font-weight:600;">{due_date}</td>
                        </tr>
                        <tr><td colspan="2" style="border-top:1px solid #e2e8f0;padding:8px 0;"></td></tr>
                        <tr>
                            <td style="font-size:15px;color:#111827;font-weight:700;">Total Due</td>
                            <td style="font-size:18px;color:{brand_colour};text-align:right;font-weight:800;">{total}</td>
                        </tr>
                    </table>
                </div>

                <!-- View button -->
                {'<div style="text-align:center;margin-bottom:24px;"><a href="' + view_url + '" style="display:inline-block;background:' + brand_colour + ';color:white;padding:14px 32px;border-radius:8px;font-weight:700;font-size:15px;text-decoration:none;">View Invoice</a></div>' if view_url else ''}

                {bank_details}

                <p style="color:#9ca3af;font-size:12px;margin:24px 0 0;line-height:1.6;">
                    A PDF copy of your invoice is attached to this email for your records.
                    {'If you have any questions, please reply to this email.' if user.email else ''}
                </p>
            </td></tr>

            <!-- Footer -->
            <tr><td style="background:#f8fafc;border-radius:0 0 12px 12px;padding:16px 32px;text-align:center;">
                <p style="color:#9ca3af;font-size:11px;margin:0;">Powered by GoZappify &middot; gozappify.com</p>
            </td></tr>

        </table>
    </td></tr>
</table>
</body>
</html>"""


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


def send_quote_email(user, quote, pdf_bytes, accept_url):
    """Send quote email to customer with PDF attachment and accept link"""
    customer = quote.customer
    if not customer or not customer.email:
        raise ValueError("Customer has no email address")

    subject = f"Quote {quote.quote_number} from {user.company_name or 'Your Contractor'}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {user.invoice_colour or '#2563eb'}; padding: 24px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">{user.company_name or 'Your Contractor'}</h1>
        </div>
        <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 8px 8px; border: 1px solid #e5e7eb;">
            <p style="color: #374151;">Dear {customer.display_name},</p>
            <p style="color: #374151;">Please find attached your quote <strong>{quote.quote_number}</strong>
            for a total of <strong>£{quote.total:.2f}</strong>.</p>
            {"<p style='color: #6b7280; font-size: 14px;'>This quote is valid until " + quote.expiry_date.strftime('%d %B %Y') + ".</p>" if quote.expiry_date else ""}
            <div style="text-align: center; margin: 32px 0;">
                <a href="{accept_url}" style="background: {user.invoice_colour or '#2563eb'}; color: white;
                   padding: 14px 32px; border-radius: 8px; text-decoration: none;
                   font-weight: bold; font-size: 16px; display: inline-block;">
                    ✓ Accept This Quote
                </a>
            </div>
            <p style="color: #6b7280; font-size: 13px; text-align: center;">
                Or open this link: <a href="{accept_url}" style="color: {user.invoice_colour or '#2563eb'};">{accept_url}</a>
            </p>
            {f'<div style="background: white; border-left: 3px solid {user.invoice_colour or "#2563eb"}; padding: 12px; margin: 16px 0; border-radius: 0 4px 4px 0;"><p style="color: #374151; margin: 0; font-size: 14px;">{quote.notes}</p></div>' if quote.notes else ''}
            <p style="color: #6b7280; font-size: 13px;">The full quote is attached as a PDF for your records.</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
            <p style="color: #9ca3af; font-size: 12px;">{user.company_name or ''}</p>
        </div>
    </div>
    """

    connection = get_email_connection(user)
    if not connection:
        raise ValueError("No email account connected. Please set up email in Settings.")

    # Build a minimal invoice-like object for the sending functions
    class _QuoteMailCtx:
        def __init__(self):
            self.customer = customer
    ctx = _QuoteMailCtx()

    if connection.provider == 'gmail':
        success, msg = _send_via_gmail(connection, user, ctx, subject, html, '', pdf_bytes)
    else:
        success, msg = _send_via_smtp(connection, user, ctx, subject, html, '', pdf_bytes)

    if not success:
        raise ValueError(msg)

def send_reminder_email(user, invoice, pdf_bytes=None):
    """Send payment reminder email to customer for outstanding invoice"""
    customer = invoice.customer
    if not customer or not customer.email:
        raise ValueError("Customer has no email address")

    days_overdue = 0
    if invoice.due_date:
        from datetime import date
        delta = date.today() - invoice.due_date
        days_overdue = max(0, delta.days)

    if days_overdue > 0:
        subject = f"Payment Reminder — {invoice.invoice_number} ({days_overdue} days overdue)"
        urgency = f"<p style='color: #dc2626; font-weight: bold;'>This invoice is now {days_overdue} days overdue.</p>"
    else:
        subject = f"Payment Reminder — {invoice.invoice_number}"
        urgency = f"<p style='color: #6b7280;'>This invoice is due on {invoice.due_date.strftime('%d %B %Y') if invoice.due_date else 'soon'}.</p>"

    brand = user.invoice_colour or '#2563eb'

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {brand}; padding: 24px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">{user.company_name or 'Your Contractor'}</h1>
            <p style="color: rgba(255,255,255,0.8); margin: 4px 0 0; font-size: 14px;">Payment Reminder</p>
        </div>
        <div style="background: #f9fafb; padding: 24px; border-radius: 0 0 8px 8px; border: 1px solid #e5e7eb;">
            <p style="color: #374151;">Dear {customer.display_name},</p>
            <p style="color: #374151;">This is a friendly reminder that invoice <strong>{invoice.invoice_number}</strong>
            for <strong>£{invoice.total:.2f}</strong> remains outstanding.</p>
            {urgency}
            <div style="background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 20px 0;">
                <table style="width: 100%; font-size: 14px;">
                    <tr><td style="color: #6b7280; padding: 4px 0;">Invoice Number</td><td style="color: #111827; font-weight: bold; text-align: right;">{invoice.invoice_number}</td></tr>
                    <tr><td style="color: #6b7280; padding: 4px 0;">Amount Due</td><td style="color: #111827; font-weight: bold; text-align: right;">£{invoice.total:.2f}</td></tr>
                    {"<tr><td style='color: #6b7280; padding: 4px 0;'>Due Date</td><td style='color: #dc2626; font-weight: bold; text-align: right;'>" + invoice.due_date.strftime('%d %B %Y') + "</td></tr>" if invoice.due_date else ""}
                </table>
            </div>
            {"<div style='background: #f3f4f6; border-radius: 8px; padding: 12px 16px; margin: 16px 0;'><p style='color: #374151; margin: 0; font-size: 13px; font-weight: bold;'>Payment Details</p>" + ("<p style='color: #374151; margin: 4px 0 0; font-size: 13px;'>Bank: " + (user.bank_name or '') + "</p>" if user.bank_name else "") + ("<p style='color: #374151; margin: 4px 0 0; font-size: 13px;'>Account: " + (user.bank_account_number or '') + "</p>" if user.bank_account_number else "") + ("<p style='color: #374151; margin: 4px 0 0; font-size: 13px;'>Sort Code: " + (user.bank_sort_code or '') + "</p>" if user.bank_sort_code else "") + ("<p style='color: #374151; margin: 4px 0 0; font-size: 13px;'>IBAN: " + (user.bank_iban or '') + "</p>" if user.bank_iban else "") + "</div>" if (user.bank_name or user.bank_account_number or user.bank_iban) else ""}
            <p style="color: #6b7280; font-size: 13px;">If you have already made payment please disregard this reminder.
            If you have any queries please don't hesitate to get in touch.</p>
            <p style="color: #6b7280; font-size: 13px; margin-top: 16px;">The invoice is attached for your reference.</p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
            <p style="color: #9ca3af; font-size: 12px;">{user.company_name or ''}</p>
        </div>
    </div>
    """

    connection = get_email_connection(user)
    if not connection:
        raise ValueError("No email account connected. Please set up email in Settings.")

    if connection.provider == 'gmail':
        success, msg = _send_via_gmail(connection, user, invoice, subject, html, '', pdf_bytes)
    else:
        success, msg = _send_via_smtp(connection, user, invoice, subject, html, '', pdf_bytes)

    if not success:
        raise ValueError(msg)
