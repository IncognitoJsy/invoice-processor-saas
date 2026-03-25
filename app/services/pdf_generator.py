"""PDF Invoice Generator - 6 templates using ReportLab"""
import io
import logging
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, KeepTogether)

logger = logging.getLogger(__name__)


def _get_logo_image(user):
    """Return a ReportLab Image from user's base64 logo_url, or None"""
    try:
        if not user.logo_url or not user.logo_url.startswith('data:'):
            return None
        import base64
        import io
        from reportlab.platypus import Image as RLImage
        # Strip data URL header
        header, b64data = user.logo_url.split(',', 1)
        img_bytes = base64.b64decode(b64data)
        buf = io.BytesIO(img_bytes)
        img = RLImage(buf)
        # Scale to max 40mm wide, 15mm tall
        max_w = 40 * mm
        max_h = 15 * mm
        ratio = min(max_w / img.drawWidth, max_h / img.drawHeight)
        img.drawWidth = img.drawWidth * ratio
        img.drawHeight = img.drawHeight * ratio
        return img
    except Exception as e:
        logger.warning(f"Could not load logo: {e}")
        return None
DEFAULT_BRAND = '#2563eb'

TEMPLATES = {
    'classic':      'Classic',
    'minimal':      'Minimal',
    'bold':         'Bold',
    'professional': 'Professional',
    'modern':       'Modern',
    'branded':      'Branded',
}


def generate_invoice_pdf(invoice, user):
    """Generate PDF and return bytes. Template selected from user.invoice_template."""
    template = getattr(user, 'invoice_template', 'classic') or 'classic'
    brand = _brand(user)

    generators = {
        'classic':      _build_classic,
        'minimal':      _build_minimal,
        'bold':         _build_bold,
        'professional': _build_professional,
        'modern':       _build_modern,
        'branded':      _build_branded,
    }
    builder = generators.get(template, _build_classic)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm,
                            title=f"Invoice {invoice.invoice_number}",
                            author=user.company_name or 'GoZappify')
    story = builder(invoice, user, brand)
    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _brand(user):
    try:
        raw = (getattr(user, 'invoice_colour', None) or DEFAULT_BRAND).strip().lstrip('#')
        # Reject named colours like 'white', 'black' etc
        if not all(c in '0123456789abcdefABCDEF' for c in raw):
            raw = DEFAULT_BRAND.lstrip('#')
        if len(raw) == 3:
            raw = ''.join(c*2 for c in raw)
        if len(raw) != 6:
            raw = DEFAULT_BRAND.lstrip('#')
        return HexColor(f'#{raw}')
    except Exception:
        return HexColor(DEFAULT_BRAND)

def _lighten(colour, factor=0.93):
    r = int(colour.red * 255); g = int(colour.green * 255); b = int(colour.blue * 255)
    r = int(r + (255 - r) * factor); g = int(g + (255 - g) * factor); b = int(b + (255 - b) * factor)
    return HexColor(f'#{r:02x}{g:02x}{b:02x}')

def _esc(t):
    if not t: return ''
    return str(t).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def _fmt_money(v):
    return f'£{float(v or 0):.2f}'

def _date(d):
    return d.strftime('%d %b %Y') if d else '—'

def _p(text, size=9, colour='#374151', bold=False, align=TA_LEFT, leading=None):
    if isinstance(colour, str):
        try:
            tc = HexColor(colour)
        except Exception:
            tc = HexColor('#374151')
    else:
        tc = colour  # already a HexColor/Color object
    return Paragraph(_esc(text), ParagraphStyle('_',
        fontSize=size,
        textColor=tc,
        fontName='Helvetica-Bold' if bold else 'Helvetica',
        alignment=align,
        leading=leading or size*1.4,
    ))

def _label(text, align=TA_LEFT):
    return Paragraph(_esc(text).upper(), ParagraphStyle('lbl',
        fontSize=7, textColor=HexColor('#9ca3af'),
        fontName='Helvetica-Bold', alignment=align,
        leading=10, letterSpacing=0.5, spaceAfter=1,
    ))

def _lines_table(invoice, brand, light, show_border=True):
    """Standard line items table used by most templates"""
    rows = [['Description', 'Qty', 'Unit Price', 'Total']]
    for line in invoice.lines:
        qty = str(int(line.quantity) if line.quantity == int(line.quantity) else line.quantity)
        rows.append([_esc(line.description or ''), qty,
                     _fmt_money(line.unit_price), _fmt_money(line.line_total)])

    cw = [100*mm, 20*mm, 30*mm, 30*mm]
    t = Table([[r[0], r[1], r[2], r[3]] for r in rows], colWidths=cw, repeatRows=1)
    s = [
        ('BACKGROUND', (0,0), (-1,0), brand),
        ('TEXTCOLOR', (0,0), (-1,0), white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('TOPPADDING', (0,0), (-1,0), 3*mm),
        ('BOTTOMPADDING', (0,0), (-1,0), 3*mm),
        ('LEFTPADDING', (0,0), (0,-1), 3*mm),
        ('RIGHTPADDING', (-1,0), (-1,-1), 3*mm),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('TOPPADDING', (0,1), (-1,-1), 2.5*mm),
        ('BOTTOMPADDING', (0,1), (-1,-1), 2.5*mm),
        ('TEXTCOLOR', (0,1), (-1,-1), HexColor('#374151')),
        ('FONTNAME', (-1,1), (-1,-1), 'Helvetica-Bold'),
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [white, HexColor('#f9fafb')]),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, HexColor('#e5e7eb')),
    ]
    t.setStyle(TableStyle(s))
    return t

def _totals_block(invoice, user, brand, align=TA_RIGHT):
    rows = []
    if invoice.tax_rate and invoice.tax_rate > 0:
        rows += [
            [_p('Subtotal', 9, '#6b7280', align=align),
             _p(_fmt_money(invoice.subtotal), 9, '#374151', True, align)],
            [_p(f'{user.tax_type or "Tax"} ({invoice.tax_rate}%)', 9, '#6b7280', align=align),
             _p(_fmt_money(invoice.tax_amount), 9, '#374151', True, align)],
        ]
    rows.append([
        _p('TOTAL DUE', 13, '#111827', True, align),
        _p(_fmt_money(invoice.total), 15, brand, True, align),
    ])
    t = Table(rows, colWidths=[130*mm, 30*mm])
    t.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('TOPPADDING', (0,0), (-1,-1), 2*mm),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, HexColor('#111827')),
    ]))
    return t

def _bank_block(invoice, user, brand, align=TA_CENTER):
    cols = []
    for lbl, val in [
        ('Bank', user.bank_name),
        ('Account Name', user.bank_account_name),
        ('Account No', user.bank_account_number),
        ('Sort Code', user.bank_sort_code),
    ]:
        if val:
            cols.append([[_label(lbl, align), _p(val, 9, '#111827', True, align)]])
    
    story = [
        HRFlowable(width='100%', thickness=1.5, color=HexColor('#111827'), spaceAfter=3*mm),
        _p('PAYMENT DETAILS', 8, '#111827', True, TA_CENTER),
        Spacer(1, 3*mm),
    ]
    if cols:
        cw = 180*mm / len(cols)
        flat = [[item[0] for item in cols]]
        t = Table(flat, colWidths=[cw]*len(cols))
        t.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),
                                ('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.append(t)
    if user.bank_iban:
        story += [Spacer(1,2*mm),
                  _p(f'IBAN: {user.bank_iban}', 9, '#111827', True, TA_CENTER)]
    story += [Spacer(1,3*mm),
              _p(f'Please use {invoice.invoice_number} as your payment reference',
                 8, '#9ca3af', align=TA_CENTER)]
    return KeepTogether(story)


# ── Template 1: Classic ───────────────────────────────────────────────────────
def _build_classic(invoice, user, brand):
    light = _lighten(brand)
    story = []

    # Build left column of header - logo + company name
    left_col = []
    logo = _get_logo_image(user)
    if logo:
        left_col.append(logo)
        left_col.append(Spacer(1, 2*mm))
    left_col.append(_p(user.company_name or 'Your Company', 16, 'white', True))
    if user.trade_type:
        left_col.append(_p(user.trade_type.title(), 9, '#bfdbfe'))
    if user.tax_registered and user.tax_number:
        left_col.append(_p(f'{user.tax_type or "Tax"} No: {user.tax_number}', 8, '#bfdbfe'))

    # Header band
    hdr = Table([[
        left_col,
        [_p(invoice.invoice_number, 22, 'white', True, TA_RIGHT),
         _p('INVOICE', 8, '#bfdbfe', align=TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), brand),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(0,-1),6*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),6*mm),
        ('TOPPADDING',(0,0),(-1,-1),6*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),6*mm),
    ]))
    story.append(hdr)

    # Bill to + dates band
    info = Table([[
        [_label('Bill To'), _p(invoice.customer.display_name, 11, '#111827', True),
         _p(invoice.customer.email or '', 8, '#6b7280'),
         _p(invoice.customer.full_address or '', 8, '#6b7280')],
        [_label('Issue Date', TA_RIGHT), _p(_date(invoice.issue_date), 10, '#111827', True, TA_RIGHT),
         Spacer(1,2*mm),
         _label('Due Date', TA_RIGHT), _p(_date(invoice.due_date), 10, '#111827', True, TA_RIGHT),
         Spacer(1,1*mm),
         _p(invoice.payment_terms_label, 8, '#6b7280', align=TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    info.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), light),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(0,-1),6*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),6*mm),
        ('TOPPADDING',(0,0),(-1,-1),5*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),5*mm),
    ]))
    story.append(info)
    story.append(Spacer(1, 5*mm))
    story.append(_lines_table(invoice, brand, light))
    story.append(Spacer(1, 4*mm))
    story.append(_totals_block(invoice, user, brand))
    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    if user.bank_account_number or user.bank_iban:
        story += [Spacer(1,5*mm), _bank_block(invoice, user, brand)]
    return story


# ── Template 2: Minimal ───────────────────────────────────────────────────────
def _build_minimal(invoice, user, brand):
    story = []

    # Simple top line — company left, invoice number right
    left_minimal = []
    logo = _get_logo_image(user)
    if logo:
        left_minimal.append(logo)
        left_minimal.append(Spacer(1, 2*mm))
    left_minimal.append(_p(user.company_name or 'Your Company', 18, '#111827', True))
    left_minimal.append(_p(user.trade_type.title() if user.trade_type else '', 9, '#9ca3af'))
    top = Table([[
        left_minimal,
        [_p(invoice.invoice_number, 24, brand, True, TA_RIGHT),
         _p('INVOICE', 8, '#9ca3af', align=TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    top.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    story.append(top)
    story.append(Spacer(1,2*mm))
    story.append(HRFlowable(width='100%', thickness=1, color=brand, spaceAfter=5*mm))

    # Bill to + dates
    details = Table([[
        [_label('Bill To'), _p(invoice.customer.display_name, 11, '#111827', True),
         _p(invoice.customer.email or '', 8, '#6b7280')],
        [_label('Date', TA_RIGHT), _p(_date(invoice.issue_date), 9, '#374151', True, TA_RIGHT),
         Spacer(1,2*mm),
         _label('Due', TA_RIGHT), _p(_date(invoice.due_date), 9, '#374151', True, TA_RIGHT),
         Spacer(1,1*mm),
         _p(invoice.payment_terms_label, 8, '#9ca3af', align=TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(details)
    story.append(Spacer(1, 6*mm))

    # Items — minimal styling, no colour header
    rows = [['Description', 'Qty', 'Unit Price', 'Total']]
    for line in invoice.lines:
        qty = str(int(line.quantity) if line.quantity == int(line.quantity) else line.quantity)
        rows.append([_esc(line.description or ''), qty,
                     _fmt_money(line.unit_price), _fmt_money(line.line_total)])
    t = Table([[r[0],r[1],r[2],r[3]] for r in rows], colWidths=[100*mm,20*mm,30*mm,30*mm])
    t.setStyle(TableStyle([
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('FONTSIZE',(0,0),(-1,0),8),
        ('TEXTCOLOR',(0,0),(-1,0), HexColor('#9ca3af')),
        ('LINEBELOW',(0,0),(-1,0),0.5, HexColor('#e5e7eb')),
        ('FONTSIZE',(0,1),(-1,-1),9),
        ('TEXTCOLOR',(0,1),(-1,-1), HexColor('#374151')),
        ('LINEBELOW',(0,1),(-1,-1),0.5, HexColor('#f3f4f6')),
        ('TOPPADDING',(0,0),(-1,-1),2.5*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),2.5*mm),
        ('ALIGN',(1,0),(-1,-1),'RIGHT'),
        ('FONTNAME',(-1,1),(-1,-1),'Helvetica-Bold'),
    ]))
    story.append(t)
    story.append(Spacer(1,4*mm))
    story.append(_totals_block(invoice, user, brand))
    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    if user.bank_account_number or user.bank_iban:
        story += [Spacer(1,5*mm), _bank_block(invoice, user, brand)]
    return story


# ── Template 3: Bold ─────────────────────────────────────────────────────────
def _build_bold(invoice, user, brand):
    story = []

    # Full width bold header
    hdr = Table([[
        _p(invoice.invoice_number, 36, 'white', True, TA_LEFT),
    ]], colWidths=[180*mm])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), brand),
        ('LEFTPADDING',(0,0),(-1,-1),8*mm),
        ('RIGHTPADDING',(0,0),(-1,-1),8*mm),
        ('TOPPADDING',(0,0),(-1,-1),8*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),2*mm),
    ]))
    story.append(hdr)

    bold_left = []
    logo = _get_logo_image(user)
    if logo:
        bold_left.append(logo)
        bold_left.append(Spacer(1, 2*mm))
    bold_left.append(_p(user.company_name or 'Your Company', 11, 'white', True))
    sub = Table([[
        bold_left,
        _p('', 10, 'white'),
    ]], colWidths=[90*mm, 90*mm])
    sub.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), brand),
        ('LEFTPADDING',(0,0),(0,-1),8*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),8*mm),
        ('TOPPADDING',(0,0),(-1,-1),0),
        ('BOTTOMPADDING',(0,0),(-1,-1),6*mm),
    ]))
    story.append(sub)
    story.append(Spacer(1,5*mm))

    # Bill to + dates
    details = Table([[
        [_label('Bill To'),
         _p(invoice.customer.display_name, 12, '#111827', True),
         _p(invoice.customer.email or '', 9, '#6b7280')],
        [_label('Issue Date', TA_RIGHT), _p(_date(invoice.issue_date), 10, '#111827', True, TA_RIGHT),
         Spacer(1,2*mm),
         _label('Due Date', TA_RIGHT), _p(_date(invoice.due_date), 10, '#111827', True, TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    details.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(details)
    story.append(Spacer(1,6*mm))
    story.append(_lines_table(invoice, brand, _lighten(brand)))
    story.append(Spacer(1,4*mm))
    story.append(_totals_block(invoice, user, brand))
    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    if user.bank_account_number or user.bank_iban:
        story += [Spacer(1,5*mm), _bank_block(invoice, user, brand)]
    return story


# ── Template 4: Professional ─────────────────────────────────────────────────
def _build_professional(invoice, user, brand):
    """Two column — sidebar left with company + bank, content right"""
    story = []
    light = _lighten(brand, 0.95)

    # Header — company left sidebar, invoice details right
    sidebar = []
    logo = _get_logo_image(user)
    if logo:
        sidebar.append(logo)
        sidebar.append(Spacer(1, 2*mm))
    sidebar += [
        _p(user.company_name or 'Your Company', 14, 'white', True),
        Spacer(1, 2*mm),
    ]
    if user.trade_type:
        sidebar.append(_p(user.trade_type.title(), 9, '#bfdbfe'))
    if user.tax_number:
        sidebar += [Spacer(1,2*mm), _p(f'{user.tax_type or "Tax"}: {user.tax_number}', 8, '#bfdbfe')]

    main = [
        _p(invoice.invoice_number, 20, 'white', True, TA_RIGHT),
        _p('INVOICE', 8, '#bfdbfe', align=TA_RIGHT),
        Spacer(1,3*mm),
        _p(_date(invoice.issue_date), 9, '#e0f2fe', align=TA_RIGHT),
        _p(f'Due: {_date(invoice.due_date)}', 9, '#fbbf24', True, TA_RIGHT),
    ]

    hdr = Table([[sidebar, main]], colWidths=[70*mm, 110*mm])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), brand),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(0,-1),6*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),6*mm),
        ('TOPPADDING',(0,0),(-1,-1),6*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),6*mm),
        ('LINEAFTER',(0,0),(0,-1), 0.5, HexColor('#bfdbfe')),
    ]))
    story.append(hdr)
    story.append(Spacer(1,5*mm))

    # Bill to full width
    bill = Table([[
        [_label('Bill To'), _p(invoice.customer.display_name, 11, '#111827', True),
         _p(invoice.customer.email or '', 8, '#6b7280'),
         _p(invoice.customer.full_address or '', 8, '#6b7280')],
        [_label('Terms', TA_RIGHT), _p(invoice.payment_terms_label, 9, '#374151', True, TA_RIGHT)],
    ]], colWidths=[120*mm, 60*mm])
    bill.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), light),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(0,-1),4*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),4*mm),
        ('TOPPADDING',(0,0),(-1,-1),4*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),4*mm),
    ]))
    story.append(bill)
    story.append(Spacer(1,5*mm))
    story.append(_lines_table(invoice, brand, light))
    story.append(Spacer(1,4*mm))
    story.append(_totals_block(invoice, user, brand))
    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    if user.bank_account_number or user.bank_iban:
        story += [Spacer(1,5*mm), _bank_block(invoice, user, brand)]
    return story


# ── Template 5: Modern ───────────────────────────────────────────────────────
def _build_modern(invoice, user, brand):
    """Left accent bar, mostly white, clean typography"""
    story = []

    # Top — no background, just text and accent line
    left_modern = []
    logo = _get_logo_image(user)
    if logo:
        left_modern.append(logo)
        left_modern.append(Spacer(1, 2*mm))
    left_modern.append(_p(user.company_name or 'Your Company', 16, '#111827', True))
    left_modern.append(_p(user.trade_type.title() if user.trade_type else '', 9, '#9ca3af'))
    top = Table([[
        left_modern,
        [_p(invoice.invoice_number, 22, brand, True, TA_RIGHT),
         _p('INVOICE', 8, '#9ca3af', align=TA_RIGHT),
         ],
    ]], colWidths=[95*mm, 85*mm])
    top.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(top)
    story.append(Spacer(1,2*mm))

    # Thick accent rule
    story.append(HRFlowable(width='100%', thickness=3, color=brand, spaceAfter=5*mm))

    # Bill to + dates with left accent bar effect using table
    left_accent = Table([[
        Table([[
            [_label('Bill To'),
             _p(invoice.customer.display_name, 11, '#111827', True),
             _p(invoice.customer.email or '', 8, '#6b7280')]
        ]], colWidths=[85*mm]),
        Table([[
            [_label('Issue Date', TA_RIGHT), _p(_date(invoice.issue_date), 9, '#374151', True, TA_RIGHT),
             Spacer(1,2*mm),
             _label('Due Date', TA_RIGHT), _p(_date(invoice.due_date), 9, brand, True, TA_RIGHT),
             Spacer(1,1*mm),
             _p(invoice.payment_terms_label, 8, '#9ca3af', align=TA_RIGHT)]
        ]], colWidths=[85*mm]),
    ]], colWidths=[95*mm, 85*mm])
    left_accent.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(left_accent)
    story.append(Spacer(1,6*mm))
    story.append(_lines_table(invoice, brand, _lighten(brand)))
    story.append(Spacer(1,4*mm))
    story.append(_totals_block(invoice, user, brand))
    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    if user.bank_account_number or user.bank_iban:
        story += [Spacer(1,5*mm), _bank_block(invoice, user, brand)]
    return story


# ── Template 6: Branded ───────────────────────────────────────────────────────
def _build_branded(invoice, user, brand):
    """Full colour header AND footer, logo prominent"""
    story = []
    light = _lighten(brand, 0.92)

    # Large header
    hdr = Table([[
        [_get_logo_image(user) or _p('', 8, 'white'),
         _p(user.company_name or 'Your Company', 20, 'white', True),
         _p(user.trade_type.title() if user.trade_type else '', 10, '#bfdbfe'),
         Spacer(1,3*mm),
         _p(f'Issue Date: {_date(invoice.issue_date)}', 8, '#e0f2fe'),
         _p(f'Due: {_date(invoice.due_date)}', 8, '#fbbf24', True)],
        [_p(invoice.invoice_number, 28, 'white', True, TA_RIGHT),
         _p('INVOICE', 9, '#bfdbfe', align=TA_RIGHT),
         Spacer(1,3*mm),

         _p(invoice.payment_terms_label, 8, '#bfdbfe', align=TA_RIGHT)],
    ]], colWidths=[95*mm, 85*mm])
    hdr.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), brand),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(0,-1),8*mm),
        ('RIGHTPADDING',(-1,0),(-1,-1),8*mm),
        ('TOPPADDING',(0,0),(-1,-1),8*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),8*mm),
    ]))
    story.append(hdr)

    # Bill to on light background
    bill = Table([[
        [_label('Bill To'), _p(invoice.customer.display_name, 12, '#111827', True),
         _p(invoice.customer.email or '', 9, '#6b7280'),
         _p(invoice.customer.full_address or '', 8, '#6b7280')],
    ]], colWidths=[180*mm])
    bill.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), light),
        ('LEFTPADDING',(0,0),(-1,-1),8*mm),
        ('TOPPADDING',(0,0),(-1,-1),5*mm),
        ('BOTTOMPADDING',(0,0),(-1,-1),5*mm),
    ]))
    story.append(bill)
    story.append(Spacer(1,5*mm))
    story.append(_lines_table(invoice, brand, light))
    story.append(Spacer(1,4*mm))
    story.append(_totals_block(invoice, user, brand))

    # Branded footer with bank details in colour band
    if user.bank_account_number or user.bank_iban:
        story.append(Spacer(1,5*mm))
        bank_items = []
        for lbl, val in [('Bank', user.bank_name), ('Account Name', user.bank_account_name),
                          ('Account No', user.bank_account_number), ('Sort Code', user.bank_sort_code)]:
            if val:
                bank_items.append([[_p(lbl.upper(), 7, '#bfdbfe', align=TA_CENTER),
                                    _p(val, 9, 'white', True, TA_CENTER)]])
        if bank_items:
            cw = 180*mm / len(bank_items)
            inner = [[item[0] for item in bank_items]]
            t = Table(inner, colWidths=[cw]*len(bank_items))
            t.setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),
                                    ('VALIGN',(0,0),(-1,-1),'TOP')]))

            footer = Table([[
                [_p('PAYMENT DETAILS', 8, 'white', True, TA_CENTER),
                 Spacer(1,3*mm),
                 t,
                 Spacer(1,2*mm),
                 _p(f'Reference: {invoice.invoice_number}', 8, '#bfdbfe', align=TA_CENTER)]
            ]], colWidths=[180*mm])
            footer.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,-1), brand),
                ('LEFTPADDING',(0,0),(-1,-1),8*mm),
                ('RIGHTPADDING',(0,0),(-1,-1),8*mm),
                ('TOPPADDING',(0,0),(-1,-1),6*mm),
                ('BOTTOMPADDING',(0,0),(-1,-1),6*mm),
            ]))
            story.append(footer)

    if invoice.notes or user.invoice_notes:
        story += [Spacer(1,4*mm), _p(invoice.notes or user.invoice_notes or '', 8, '#9ca3af', align=TA_CENTER)]
    return story
