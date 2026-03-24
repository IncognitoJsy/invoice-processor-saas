"""PDF Invoice Generator using ReportLab
Generates professional A4 invoice PDFs for GoZappify full platform mode
"""
import io
import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.platypus import KeepTogether
from reportlab.lib import colors

logger = logging.getLogger(__name__)

# Default brand colour — overridden by user's invoice_colour
DEFAULT_BRAND = '#2563eb'


def generate_invoice_pdf(invoice, user):
    """Generate a PDF invoice and return bytes.
    
    Args:
        invoice: CustomerInvoice model instance
        user: User model instance
    
    Returns:
        bytes: PDF file content
    """
    buffer = io.BytesIO()
    
    # Page setup
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm,
        title=f"Invoice {invoice.invoice_number}",
        author=user.company_name or 'GoZappify',
    )

    brand_hex = (user.invoice_colour or DEFAULT_BRAND).lstrip('#')
    brand_colour = HexColor(f'#{brand_hex}')
    light_brand = _lighten(brand_hex, 0.92)
    
    story = []
    styles = getSampleStyleSheet()

    # ── Header ──────────────────────────────────────────────────────────────
    header_data = [[
        _company_block(user, styles, brand_colour),
        _invoice_meta_block(invoice, styles, brand_colour),
    ]]
    header_table = Table(header_data, colWidths=[95*mm, 85*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), brand_colour),
        ('LEFTPADDING', (0, 0), (0, -1), 6*mm),
        ('RIGHTPADDING', (-1, 0), (-1, -1), 6*mm),
        ('TOPPADDING', (0, 0), (-1, -1), 6*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6*mm),
        ('ROUNDEDCORNERS', [4, 4, 0, 0]),
    ]))
    story.append(header_table)

    # ── Bill To + Dates ──────────────────────────────────────────────────────
    bill_to = _bill_to_block(invoice, styles)
    dates = _dates_block(invoice, styles)
    
    info_data = [[bill_to, dates]]
    info_table = Table(info_data, colWidths=[95*mm, 85*mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, -1), light_brand),
        ('LEFTPADDING', (0, 0), (0, -1), 6*mm),
        ('RIGHTPADDING', (-1, 0), (-1, -1), 6*mm),
        ('TOPPADDING', (0, 0), (-1, -1), 5*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5*mm),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 6*mm))

    # ── Line Items ───────────────────────────────────────────────────────────
    story.append(_line_items_table(invoice, styles, brand_colour, light_brand))
    story.append(Spacer(1, 4*mm))

    # ── Totals ───────────────────────────────────────────────────────────────
    story.append(_totals_table(invoice, user, styles, brand_colour))
    story.append(Spacer(1, 6*mm))

    # ── Notes ────────────────────────────────────────────────────────────────
    notes = invoice.notes or user.invoice_notes
    if notes:
        note_style = ParagraphStyle('note', fontSize=8, textColor=HexColor('#6b7280'),
                                    leading=12, alignment=TA_CENTER)
        story.append(Paragraph(notes, note_style))
        story.append(Spacer(1, 4*mm))

    # ── Bank Details ─────────────────────────────────────────────────────────
    if user.bank_account_number or user.bank_iban:
        story.append(_bank_details_table(invoice, user, styles, brand_colour))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def _company_block(user, styles, brand_colour):
    """Company name and trade type for header"""
    company = user.company_name or 'Your Company'
    paras = [
        Paragraph(f'<font color="white"><b>{_esc(company)}</b></font>',
                  ParagraphStyle('co', fontSize=16, leading=20, textColor=white)),
    ]
    if user.trade_type:
        paras.append(Paragraph(
            f'<font color="#bfdbfe">{_esc(user.trade_type.title())}</font>',
            ParagraphStyle('trade', fontSize=9, leading=12, textColor=HexColor('#bfdbfe'))))
    if user.tax_registered and user.tax_number:
        paras.append(Paragraph(
            f'<font color="#bfdbfe">{user.tax_type or "Tax"} No: {_esc(user.tax_number)}</font>',
            ParagraphStyle('tax', fontSize=8, leading=11, textColor=HexColor('#bfdbfe'))))
    return paras


def _invoice_meta_block(invoice, styles, brand_colour):
    """Invoice number and status for header"""
    status_colours = {
        'open': '#f59e0b', 'sent': '#3b82f6',
        'paid': '#10b981', 'overdue': '#ef4444', 'void': '#9ca3af'
    }
    status_col = status_colours.get(invoice.status, '#9ca3af')
    
    return [
        Paragraph(f'<font color="white"><b>{_esc(invoice.invoice_number)}</b></font>',
                  ParagraphStyle('invno', fontSize=22, leading=26, alignment=TA_RIGHT,
                                 textColor=white)),
        Paragraph('<font color="#bfdbfe">INVOICE</font>',
                  ParagraphStyle('invlbl', fontSize=9, leading=12, alignment=TA_RIGHT,
                                 textColor=HexColor('#bfdbfe'))),
        Spacer(1, 3*mm),
        Paragraph(f'<font color="{status_col}"><b>{invoice.status.upper()}</b></font>',
                  ParagraphStyle('status', fontSize=9, leading=12, alignment=TA_RIGHT)),
    ]


def _bill_to_block(invoice, styles):
    """Bill to section"""
    label = ParagraphStyle('lbl', fontSize=7, textColor=HexColor('#6b7280'),
                            leading=10, spaceAfter=2)
    val = ParagraphStyle('val', fontSize=10, textColor=HexColor('#111827'),
                         leading=14, fontName='Helvetica-Bold')
    sub = ParagraphStyle('sub', fontSize=8, textColor=HexColor('#6b7280'), leading=11)
    
    paras = [
        Paragraph('BILL TO', label),
        Paragraph(_esc(invoice.customer.display_name), val),
    ]
    if invoice.customer.email:
        paras.append(Paragraph(_esc(invoice.customer.email), sub))
    if invoice.customer.phone:
        paras.append(Paragraph(_esc(invoice.customer.phone), sub))
    if invoice.customer.full_address:
        paras.append(Paragraph(_esc(invoice.customer.full_address), sub))
    return paras


def _dates_block(invoice, styles):
    """Issue date, due date, terms"""
    label = ParagraphStyle('lbl2', fontSize=7, textColor=HexColor('#6b7280'),
                           leading=10, spaceAfter=1, alignment=TA_RIGHT)
    val = ParagraphStyle('val2', fontSize=9, textColor=HexColor('#111827'),
                         leading=13, fontName='Helvetica-Bold', alignment=TA_RIGHT)
    
    issue = invoice.issue_date.strftime('%d %b %Y') if invoice.issue_date else '—'
    due = invoice.due_date.strftime('%d %b %Y') if invoice.due_date else '—'
    
    return [
        Paragraph('ISSUE DATE', label),
        Paragraph(issue, val),
        Spacer(1, 2*mm),
        Paragraph('DUE DATE', label),
        Paragraph(due, val),
        Spacer(1, 2*mm),
        Paragraph('PAYMENT TERMS', label),
        Paragraph(_esc(invoice.payment_terms_label), val),
    ]


def _line_items_table(invoice, styles, brand_colour, light_brand):
    """Line items table"""
    header = ['Description', 'Qty', 'Unit Price', 'Total']
    rows = [header]
    
    for line in invoice.lines:
        rows.append([
            line.description or '',
            str(line.quantity if line.quantity != int(line.quantity) else int(line.quantity)),
            f'£{line.unit_price:.2f}',
            f'£{line.line_total:.2f}',
        ])
    
    col_widths = [100*mm, 20*mm, 30*mm, 30*mm]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    
    style = [
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), brand_colour),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 4*mm),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4*mm),
        ('LEFTPADDING', (0, 0), (0, -1), 4*mm),
        ('RIGHTPADDING', (-1, 0), (-1, -1), 4*mm),
        # Data rows
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 3*mm),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3*mm),
        ('TEXTCOLOR', (0, 1), (-1, -1), HexColor('#374151')),
        ('FONTNAME', (-1, 1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (-1, 1), (-1, -1), HexColor('#111827')),
        # Alignment
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        # Alternating rows
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f9fafb')]),
        # Grid
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
        ('LINEBELOW', (0, 0), (-1, 0), 0, white),
    ]
    t.setStyle(TableStyle(style))
    return t


def _totals_table(invoice, user, styles, brand_colour):
    """Totals section aligned right"""
    rows = []
    
    if invoice.tax_rate and invoice.tax_rate > 0:
        rows.append(['Subtotal', f'£{invoice.subtotal:.2f}'])
        rows.append([f'{user.tax_type or "Tax"} ({invoice.tax_rate}%)', f'£{invoice.tax_amount:.2f}'])
    
    rows.append(['TOTAL DUE', f'£{invoice.total:.2f}'])
    
    col_widths = [130*mm, 30*mm]
    
    label_normal = ParagraphStyle('tn', fontSize=9, textColor=HexColor('#6b7280'),
                                  alignment=TA_RIGHT)
    label_total = ParagraphStyle('tt', fontSize=12, textColor=HexColor('#111827'),
                                 fontName='Helvetica-Bold', alignment=TA_RIGHT)
    val_normal = ParagraphStyle('vn', fontSize=9, textColor=HexColor('#374151'),
                                alignment=TA_RIGHT, fontName='Helvetica-Bold')
    val_total = ParagraphStyle('vt', fontSize=14, textColor=brand_colour,
                               alignment=TA_RIGHT, fontName='Helvetica-Bold')
    
    table_rows = []
    for i, (label, val) in enumerate(rows):
        is_total = i == len(rows) - 1
        table_rows.append([
            Paragraph(label, label_total if is_total else label_normal),
            Paragraph(val, val_total if is_total else val_normal),
        ])
    
    t = Table(table_rows, colWidths=col_widths)
    style = [
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 2*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm),
        ('LINEABOVE', (0, -1), (-1, -1), 1.5, HexColor('#111827')),
        ('TOPPADDING', (0, -1), (-1, -1), 3*mm),
    ]
    t.setStyle(TableStyle(style))
    return t


def _bank_details_table(invoice, user, styles, brand_colour):
    """Bank details centred at bottom"""
    label = ParagraphStyle('blbl', fontSize=7, textColor=HexColor('#9ca3af'),
                           leading=10, alignment=TA_CENTER,
                           fontName='Helvetica-Bold',
                           spaceAfter=1)
    val = ParagraphStyle('bval', fontSize=9, textColor=HexColor('#111827'),
                         leading=13, alignment=TA_CENTER,
                         fontName='Helvetica-Bold')
    ref_style = ParagraphStyle('ref', fontSize=8, textColor=HexColor('#9ca3af'),
                               alignment=TA_CENTER, leading=12)
    
    # Build bank detail columns
    cols = []
    if user.bank_name:
        cols.append([Paragraph('BANK', label), Paragraph(_esc(user.bank_name), val)])
    if user.bank_account_name:
        cols.append([Paragraph('ACCOUNT NAME', label), Paragraph(_esc(user.bank_account_name), val)])
    if user.bank_account_number:
        cols.append([Paragraph('ACCOUNT NO', label), Paragraph(f'<font face="Courier">{_esc(user.bank_account_number)}</font>', val)])
    if user.bank_sort_code:
        cols.append([Paragraph('SORT CODE', label), Paragraph(f'<font face="Courier">{_esc(user.bank_sort_code)}</font>', val)])
    
    story = [
        HRFlowable(width='100%', thickness=1.5, color=HexColor('#111827'), spaceAfter=4*mm),
        Paragraph('PAYMENT DETAILS', ParagraphStyle('pd', fontSize=8, fontName='Helvetica-Bold',
                  textColor=HexColor('#111827'), alignment=TA_CENTER, spaceAfter=4*mm,
                  letterSpacing=1)),
    ]
    
    if cols:
        col_width = 180*mm / len(cols)
        t = Table([cols], colWidths=[col_width] * len(cols))
        t.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2*mm),
        ]))
        story.append(t)
    
    if user.bank_iban:
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(f'IBAN: <font face="Courier"><b>{_esc(user.bank_iban)}</b></font>', 
                               ParagraphStyle('iban', fontSize=9, alignment=TA_CENTER,
                                             textColor=HexColor('#111827'))))
    
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f'Please use <b>{_esc(invoice.invoice_number)}</b> as your payment reference',
        ref_style))
    
    return KeepTogether(story)


def _lighten(hex_colour, factor=0.92):
    """Lighten a hex colour by blending with white"""
    r = int(hex_colour[0:2], 16)
    g = int(hex_colour[2:4], 16)
    b = int(hex_colour[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return HexColor(f'#{r:02x}{g:02x}{b:02x}')


def _esc(text):
    """Escape XML special characters for ReportLab"""
    if not text:
        return ''
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
