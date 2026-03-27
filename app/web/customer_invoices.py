"""Customer Invoice routes - full platform mode"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.models.product_service import ProductService
from datetime import datetime
import logging

bp = Blueprint('customer_invoices', __name__, url_prefix='/customer-invoices')
logger = logging.getLogger(__name__)


def require_full_mode(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.platform_mode not in ['full', 'both']:
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


def generate_invoice_number(user):
    """Generate next invoice number for user"""
    prefix = user.invoice_prefix or 'INV'
    num = user.next_invoice_number or 1
    user.next_invoice_number = num + 1
    return f"{prefix}-{num:03d}"


def generate_quote_number(user):
    """Generate next quote number for user"""
    prefix = user.quote_prefix or 'QUO'
    num = user.next_quote_number or 1
    user.next_quote_number = num + 1
    return f"{prefix}-{num:03d}"


def get_or_create_materials_used(user_id):
    """Get or create the 'Materials Used' summary product"""
    product = ProductService.query.filter_by(
        user_id=user_id,
        name='Materials Used'
    ).first()
    if not product:
        product = ProductService(
            user_id=user_id,
            name='Materials Used',
            description='Summary of materials used on job',
            item_type='product',
            purchase_price=0.0,
            sale_price=0.0,
        )
        db.session.add(product)
        db.session.flush()
    return product


@bp.route('/')
@login_required
@require_full_mode
def index():
    from datetime import datetime
    tab = request.args.get('tab', 'open')
    all_invoices = CustomerInvoice.query.filter_by(user_id=current_user.id).all()

    # Update overdue status for sent invoices
    from datetime import date
    today = date.today()
    changed = False
    for inv in all_invoices:
        if inv.status == 'sent' and inv.due_date:
            due = inv.due_date.date() if hasattr(inv.due_date, 'date') and callable(inv.due_date.date) else inv.due_date
            if today > due:
                inv.status = 'overdue'
                changed = True
    if changed:
        db.session.commit()

    # Split into tabs
    # Open = open or sent but not yet overdue
    open_invoices = [i for i in all_invoices if i.status in ['open', 'sent', 'viewed'] and not i.is_overdue]
    # Overdue = overdue status OR past due date
    outstanding = sorted(
        [i for i in all_invoices if i.status in ['overdue'] or (i.status not in ['paid', 'void'] and i.is_overdue)],
        key=lambda x: x.due_date or datetime.max
    )
    paid_invoices = sorted(
        [i for i in all_invoices if i.status == 'paid'],
        key=lambda x: x.paid_at or x.created_at, reverse=True
    )
    void_invoices = [i for i in all_invoices if i.status == 'void']

    counts = {
        'open': len(open_invoices),
        'outstanding': len(outstanding),
        'paid': len(paid_invoices),
        'void': len(void_invoices),
    }

    tab_invoices = {
        'open': open_invoices,
        'outstanding': outstanding,
        'paid': paid_invoices,
        'void': void_invoices,
    }.get(tab, open_invoices)

    from app.models.customer import Customer
    all_customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    return render_template('customer_invoices/index.html',
        invoices=tab_invoices,
        all_customers=all_customers,
        tab=tab,
        counts=counts,
        now=datetime.utcnow(),
    )


@bp.route('/<int:invoice_id>')
@login_required
@require_full_mode
def view(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    return render_template('customer_invoices/view.html', invoice=invoice)


@bp.route('/api/check-customer/<int:customer_id>')
@login_required
@require_full_mode
def check_customer(customer_id):
    """Check if customer has an open invoice"""
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()

    open_invoice = CustomerInvoice.query.filter_by(
        user_id=current_user.id,
        customer_id=customer_id,
        status='open'
    ).order_by(CustomerInvoice.created_at.desc()).first()

    return jsonify({
        'success': True,
        'customer': {
            'id': customer.id,
            'name': customer.display_name,
            'payment_terms': customer.payment_terms or current_user.default_payment_terms or '30',
        },
        'open_invoice': {
            'id': open_invoice.id,
            'invoice_number': open_invoice.invoice_number,
            'invoice_mode': open_invoice.invoice_mode,
            'total': open_invoice.total,
            'line_count': open_invoice.lines.count(),
            'created_at': open_invoice.created_at.isoformat(),
        } if open_invoice else None,
        'default_mode': current_user.default_invoice_mode or 'itemised',
    })


@bp.route('/api/add-supplier-invoice', methods=['POST'])
@login_required
@require_full_mode
def add_supplier_invoice():
    """Add a processed supplier invoice to a customer invoice"""
    data = request.get_json()
    customer_id = data.get('customer_id')
    supplier_invoice_id = data.get('supplier_invoice_id')
    mode = data.get('mode', 'itemised')  # itemised or summary
    use_existing = data.get('use_existing', True)  # add to open or create new

    if not customer_id or not supplier_invoice_id:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    supplier_invoice = Invoice.query.filter_by(
        id=supplier_invoice_id, user_id=current_user.id).first_or_404()

    # Get or create customer invoice
    customer_invoice = None
    if use_existing:
        customer_invoice = CustomerInvoice.query.filter_by(
            user_id=current_user.id,
            customer_id=customer_id,
            status='open'
        ).order_by(CustomerInvoice.created_at.desc()).first()

    if not customer_invoice:
        # Create new customer invoice
        customer_invoice = CustomerInvoice(
            user_id=current_user.id,
            customer_id=customer_id,
            invoice_number=generate_invoice_number(current_user),
            status='open',
            invoice_mode=mode,
            payment_terms=customer.payment_terms or current_user.default_payment_terms or '30',
            issue_date=datetime.utcnow(),
            tax_rate=current_user.tax_rate or 0.0,
        )
        customer_invoice.calculate_due_date()
        db.session.add(customer_invoice)
        db.session.flush()

    # Add items based on mode
    if mode == 'summary':
        _add_summary_line(customer_invoice, supplier_invoice)
    else:
        _add_itemised_lines(customer_invoice, supplier_invoice)

    # Recalculate totals
    customer_invoice.recalculate_totals()

    # Update supplier invoice assignment
    supplier_invoice.platform_customer_id = customer_id
    supplier_invoice.customer_match_confidence = 'manual'

    db.session.commit()

    return jsonify({
        'success': True,
        'customer_invoice': customer_invoice.to_dict(),
        'message': f'Added to {customer_invoice.invoice_number}',
    })


def _add_itemised_lines(customer_invoice, supplier_invoice):
    """Add itemised lines from supplier invoice, merging duplicates"""
    items = InvoiceItem.query.filter_by(invoice_id=supplier_invoice.id).all()

    for item in items:
        description = item.description or item.part_number or 'Material'
        unit_price = float(item.selling_price or 0)
        quantity = float(item.quantity or 1)

        # Check if this item already exists on the invoice (by description match)
        existing_line = CustomerInvoiceLine.query.filter_by(
            customer_invoice_id=customer_invoice.id,
            description=description,
            line_type='itemised'
        ).first()

        if existing_line:
            # Merge — update quantity
            existing_line.quantity = (existing_line.quantity or 0) + quantity
            existing_line.line_total = round(
                existing_line.quantity * existing_line.unit_price, 2)
        else:
            # Add new line
            line = CustomerInvoiceLine(
                customer_invoice_id=customer_invoice.id,
                source_invoice_id=supplier_invoice.id,
                description=description,
                quantity=quantity,
                unit_price=unit_price,
                line_total=round(quantity * unit_price, 2),
                line_type='itemised',
            )
            db.session.add(line)


def _add_summary_line(customer_invoice, supplier_invoice):
    """Add a summary 'Materials Used' line.
    There is always exactly ONE Materials Used line per customer invoice.
    Each new supplier invoice processed adds its total to that single line.
    """
    materials_product = get_or_create_materials_used(current_user.id)
    total_selling = float(supplier_invoice.total_selling or 0)

    # Find the single cumulative Materials Used line on this invoice
    existing = CustomerInvoiceLine.query.filter_by(
        customer_invoice_id=customer_invoice.id,
        line_type='summary'
    ).first()

    if existing:
        # Add the new supplier invoice total to the running total
        existing.unit_price = round((existing.unit_price or 0) + total_selling, 2)
        existing.line_total = existing.unit_price
    else:
        # First supplier invoice added to this customer invoice
        line = CustomerInvoiceLine(
            customer_invoice_id=customer_invoice.id,
            source_invoice_id=supplier_invoice.id,
            product_service_id=materials_product.id,
            description='Materials Used',
            quantity=1,
            unit_price=total_selling,
            line_total=total_selling,
            line_type='summary',
        )
        db.session.add(line)


@bp.route('/<int:invoice_id>/mark-sent', methods=['POST'])
@login_required
@require_full_mode
def mark_sent(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    invoice.status = 'sent'
    invoice.sent_at = datetime.utcnow()
    db.session.commit()
    flash(f'{invoice.invoice_number} marked as sent.', 'success')
    return redirect(url_for('customer_invoices.view', invoice_id=invoice.id))


@bp.route('/<int:invoice_id>/mark-paid', methods=['POST'])
@login_required
@require_full_mode
def mark_paid(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    invoice.status = 'paid'
    invoice.paid_at = datetime.utcnow()
    db.session.commit()
    flash(f'{invoice.invoice_number} marked as paid.', 'success')
    return redirect(url_for('customer_invoices.view', invoice_id=invoice.id))


@bp.route('/<int:invoice_id>/receive-payment', methods=['POST'])
@login_required
@require_full_mode
def receive_payment(invoice_id):
    """Record payment received for an invoice"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()

    data = request.get_json() or request.form
    payment_date_str = data.get('payment_date')
    payment_method = data.get('payment_method', 'bank_transfer')
    memo = data.get('memo', '') or data.get('reference', '')

    from datetime import date as date_type
    if payment_date_str:
        try:
            paid_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
        except ValueError:
            paid_date = date_type.today()
    else:
        paid_date = date_type.today()

    invoice.status = 'paid'
    invoice.paid_at = datetime.combine(paid_date, datetime.min.time())

    # Create CustomerPayment record for history tracking
    if invoice.customer_id:
        from app.models.customer_payment import CustomerPayment, CustomerInvoicePayment
        payment = CustomerPayment(
            user_id=current_user.id,
            customer_id=invoice.customer_id,
            amount=invoice.total or 0,
            payment_date=paid_date,
            payment_method=payment_method,
            reference=memo or None,
        )
        db.session.add(payment)
        db.session.flush()
        link = CustomerInvoicePayment(
            payment_id=payment.id,
            invoice_id=invoice.id,
            amount_applied=invoice.total or 0,
        )
        db.session.add(link)

    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'invoice_number': invoice.invoice_number})

    flash(f'Payment recorded for {invoice.invoice_number}.', 'success')
    return redirect(url_for('customer_invoices.index', tab='paid'))


@bp.route('/api/bulk-payment', methods=['POST'])
@login_required
@require_full_mode
def bulk_payment():
    """Record payment for multiple invoices at once"""
    data = request.get_json()
    invoice_ids = data.get('invoice_ids', [])
    payment_date = data.get('payment_date')
    payment_method = data.get('payment_method', 'bank_transfer')
    memo = data.get('memo', '')

    if not invoice_ids:
        return jsonify({'success': False, 'error': 'No invoices selected'}), 400

    paid_count = 0
    for inv_id in invoice_ids:
        invoice = CustomerInvoice.query.filter_by(
            id=inv_id, user_id=current_user.id).first()
        if invoice and invoice.status in ['open', 'sent', 'overdue']:
            invoice.status = 'paid'
            if payment_date:
                try:
                    invoice.paid_at = datetime.strptime(payment_date, '%Y-%m-%d')
                except ValueError:
                    invoice.paid_at = datetime.utcnow()
            else:
                invoice.paid_at = datetime.utcnow()
            paid_count += 1

    db.session.commit()
    return jsonify({'success': True, 'paid_count': paid_count})


@bp.route('/<int:invoice_id>/reorder-lines', methods=['POST'])
@login_required
@require_full_mode
def reorder_lines(invoice_id):
    """Update sort order of lines after drag and drop"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    line_ids = data.get('line_ids', [])
    for i, line_id in enumerate(line_ids):
        line = CustomerInvoiceLine.query.filter_by(
            id=line_id, customer_invoice_id=invoice_id).first()
        if line:
            line.sort_order = i
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:invoice_id>/update-line/<int:line_id>', methods=['POST'])
@login_required
@require_full_mode
def update_line(invoice_id, line_id):
    """Update quantity and/or unit price on an existing line"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    if invoice.status != 'open':
        return jsonify({'success': False, 'error': 'Can only edit open invoices'}), 400
    line = CustomerInvoiceLine.query.filter_by(
        id=line_id, customer_invoice_id=invoice_id).first_or_404()
    data = request.get_json()
    if 'quantity' in data:
        line.quantity = float(data['quantity'] or 0)
    if 'unit_price' in data:
        line.unit_price = float(data['unit_price'] or 0)
    line.line_total = round(line.quantity * line.unit_price, 2)
    invoice.recalculate_totals()
    db.session.commit()
    return jsonify({
        'success': True,
        'line_total': line.line_total,
        'invoice_total': invoice.total,
        'invoice_subtotal': invoice.subtotal,
    })


@bp.route('/<int:invoice_id>/update-due-date', methods=['POST'])
@login_required
@require_full_mode
def update_due_date(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    due_date_str = data.get('due_date')
    if due_date_str:
        try:
            new_due = datetime.strptime(due_date_str, '%Y-%m-%d').date()
            invoice.due_date = new_due
            # Recalculate payment terms based on days between issue and due date
            if invoice.issue_date:
                issue = invoice.issue_date
                if hasattr(issue, 'date') and callable(issue.date):
                    issue = issue.date()
                days_diff = (new_due - issue).days
                if days_diff <= 0:
                    invoice.payment_terms = '0'
                else:
                    invoice.payment_terms = str(days_diff)
            db.session.commit()
            return jsonify({'success': True, 'payment_terms_label': invoice.payment_terms_label})
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid date'}), 400
    return jsonify({'success': False, 'error': 'No date provided'}), 400


@bp.route('/<int:invoice_id>/update-issue-date', methods=['POST'])
@login_required
@require_full_mode
def update_issue_date(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    issue_date_str = data.get('issue_date')
    if issue_date_str:
        try:
            from datetime import timedelta
            new_issue = datetime.strptime(issue_date_str, '%Y-%m-%d').date()
            invoice.issue_date = new_issue
            # Recalculate due date based on stored payment terms
            terms = invoice.payment_terms or '30'
            try:
                days = int(terms)
            except ValueError:
                days = 30
            invoice.due_date = new_issue + timedelta(days=days)
            db.session.commit()
            due_formatted = invoice.due_date.strftime('%d %b %Y')
            return jsonify({
                'success': True,
                'new_due_date': invoice.due_date.strftime('%Y-%m-%d'),
                'due_formatted': due_formatted,
                'payment_terms_label': invoice.payment_terms_label
            })
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid date'}), 400
    return jsonify({'success': False, 'error': 'No date provided'}), 400


@bp.route('/<int:invoice_id>/add-line', methods=['POST'])
@login_required
@require_full_mode
def add_line(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    if invoice.status != 'open':
        return jsonify({'success': False, 'error': 'Can only add lines to open invoices'}), 400
    data = request.get_json()
    description = data.get('description', '').strip()
    quantity = float(data.get('quantity', 1) or 1)
    unit_price = float(data.get('unit_price', 0) or 0)
    if not description:
        return jsonify({'success': False, 'error': 'Description required'}), 400
    line = CustomerInvoiceLine(
        customer_invoice_id=invoice_id,
        description=description,
        quantity=quantity,
        unit_price=unit_price,
        line_total=round(quantity * unit_price, 2),
        line_type='itemised',
    )
    db.session.add(line)
    invoice.recalculate_totals()
    db.session.commit()
    return jsonify({'success': True, 'line': line.to_dict(), 'total': invoice.total})


@bp.route('/<int:invoice_id>/delete-line/<int:line_id>', methods=['POST'])
@login_required
@require_full_mode
def delete_line(invoice_id, line_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    line = CustomerInvoiceLine.query.filter_by(
        id=line_id, customer_invoice_id=invoice_id).first_or_404()
    db.session.delete(line)
    invoice.recalculate_totals()
    db.session.commit()
    return jsonify({'success': True, 'total': invoice.total})


@bp.route('/api/customer/<int:customer_id>/open-invoices')
@login_required
@require_full_mode
def customer_open_invoices(customer_id):
    """Get open invoices for a customer (for bulk payment)"""
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    invoices = CustomerInvoice.query.filter_by(
        user_id=current_user.id,
        customer_id=customer_id
    ).filter(CustomerInvoice.status.in_(['open', 'sent', 'overdue'])).all()

    return jsonify({
        'success': True,
        'customer': {'id': customer.id, 'name': customer.display_name},
        'invoices': [i.to_dict() for i in invoices]
    })


@bp.route('/api/customers')
@login_required
@require_full_mode
def get_customers():
    """Get all customers for payment selection"""
    customers = Customer.query.filter_by(user_id=current_user.id)        .order_by(Customer.name.asc()).all()
    return jsonify({
        'success': True,
        'customers': [{'id': c.id, 'name': c.display_name, 'email': c.email} for c in customers]
    })


@bp.route('/api/<int:invoice_id>/pdf')
@login_required
@require_full_mode
def download_pdf(invoice_id):
    """Generate and download invoice as PDF"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    try:
        from app.services.pdf_generator import generate_invoice_pdf
        from flask import Response
        pdf_bytes = generate_invoice_pdf(invoice, current_user)
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{invoice.invoice_number}.pdf"',
                'Content-Type': 'application/pdf',
            }
        )
    except Exception as e:
        current_app.logger.error(f"PDF generation error: {e}")
        flash('Error generating PDF. Please try again.', 'error')
        return redirect(url_for('customer_invoices.view', invoice_id=invoice_id))


@bp.route('/api/<int:invoice_id>/preview')
@login_required
@require_full_mode
def preview(invoice_id):
    """Preview invoice as it will appear to client"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    auto_print = request.args.get('print') == '1'
    return render_template('customer_invoices/preview.html',
        invoice=invoice, auto_print=auto_print)


@bp.route('/<int:invoice_id>/void', methods=['POST'])
@login_required
@require_full_mode
def void(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    invoice.status = 'void'
    db.session.commit()
    flash(f'{invoice.invoice_number} voided.', 'success')
    return redirect(url_for('customer_invoices.index'))


@bp.route('/<int:invoice_id>/send-email', methods=['POST'])
@login_required
@require_full_mode
def send_email(invoice_id):
    """Actually send invoice via connected email account"""
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()

    if not invoice.customer.email:
        if request.is_json:
            return jsonify({'success': False, 'error': f'No email address for {invoice.customer.display_name}. Please add one first.'})
        flash(f'Please add an email address for {invoice.customer.display_name} first.', 'error')
        return redirect(url_for('customers.edit', customer_id=invoice.customer_id))

    # Generate view token if not already set
    if not invoice.view_token:
        invoice.generate_view_token(expires_days=90)
        db.session.commit()

    from app.services.email_sender import send_invoice_email

    # No PDF attachment - customer views invoice via secure link
    success, message = send_invoice_email(current_user, invoice, pdf_bytes=None)

    if success:
        invoice.status = 'sent'
        invoice.sent_at = datetime.utcnow()
        db.session.commit()

    if request.is_json:
        return jsonify({'success': success, 'message': message})

    flash(message, 'success' if success else 'error')
    return redirect(url_for('customer_invoices.view', invoice_id=invoice_id))


@bp.route('/<int:invoice_id>/send-reminder', methods=['POST'])
@login_required
@require_full_mode
def send_reminder(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()

    if not invoice.customer or not invoice.customer.email:
        flash('Customer has no email address. Please update their profile first.', 'error')
        return redirect(url_for('customer_invoices.view', invoice_id=invoice_id))

    try:
        from app.services.pdf_generator import generate_invoice_pdf
        from app.services.email_sender import send_reminder_email
        pdf = generate_invoice_pdf(invoice, current_user)
        send_reminder_email(current_user, invoice, pdf)
        flash(f'Reminder sent to {invoice.customer.email} for {invoice.invoice_number}.', 'success')
    except Exception as e:
        current_app.logger.error(f"Failed to send reminder for {invoice.invoice_number}: {e}")
        flash(f'Failed to send reminder: {str(e)}', 'error')

    return redirect(url_for('customer_invoices.view', invoice_id=invoice_id))


@bp.route('/<int:invoice_id>/delete', methods=['POST'])
@login_required
@require_full_mode
def delete(invoice_id):
    invoice = CustomerInvoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()
    num = invoice.invoice_number
    db.session.delete(invoice)
    db.session.commit()
    flash(f'{num} deleted.', 'success')
    return redirect(url_for('customer_invoices.index'))


@bp.route('/new')
@login_required
@require_full_mode
def new():
    """Manual invoice creation page"""
    from app.models.customer import Customer
    from app.models.product_service import ProductService
    from datetime import date, timedelta
    customer_id = request.args.get('customer_id', type=int)
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    selected_customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first() if customer_id else None
    products = ProductService.query.filter_by(user_id=current_user.id).order_by(ProductService.name).all()
    today = date.today()
    default_terms = current_user.default_payment_terms or '30'
    try:
        due_date = today + timedelta(days=int(default_terms))
    except:
        due_date = today + timedelta(days=30)
    return render_template('customer_invoices/new.html',
        customers=customers,
        selected_customer=selected_customer,
        products=products,
        today=today.strftime('%Y-%m-%d'),
        default_due=due_date.strftime('%Y-%m-%d'),
        default_expiry=due_date.strftime('%Y-%m-%d'),
        default_terms=default_terms,
        next_number=f"{current_user.invoice_prefix or 'INV'}-{current_user.next_invoice_number or 1:03d}",
        doc_type='invoice',
        back_url=url_for('customer_invoices.index'),
    )


@bp.route('/create-manual', methods=['POST'])
@login_required
@require_full_mode
def create_manual():
    """Create invoice from manual entry"""
    from datetime import date, timedelta
    data = request.get_json()
    inv_num = current_user.next_invoice_number or 1
    current_user.next_invoice_number = inv_num + 1
    invoice_number = f"{current_user.invoice_prefix or 'INV'}-{inv_num:03d}"
    try:
        issue = datetime.strptime(data['issue_date'], '%Y-%m-%d').date()
        due = datetime.strptime(data['due_date'], '%Y-%m-%d').date()
    except:
        issue = date.today()
        due = date.today() + timedelta(days=30)
    invoice = CustomerInvoice(
        user_id=current_user.id,
        customer_id=data['customer_id'],
        invoice_number=invoice_number,
        status='open',
        issue_date=issue,
        due_date=due,
        subtotal=data.get('subtotal', 0),
        tax_rate=data.get('tax_rate', 0),
        tax_amount=data.get('tax_amount', 0),
        total=data.get('total', 0),
        notes=data.get('notes', ''),
        payment_terms=data.get('payment_terms', '30'),
    )
    db.session.add(invoice)
    db.session.flush()
    for line in data.get('lines', []):
        inv_line = CustomerInvoiceLine(
            customer_invoice_id=invoice.id,
            description=line['description'],
            quantity=line['quantity'],
            unit_price=line['unit_price'],
            line_total=line['line_total'],
            sort_order=line.get('sort_order', 0),
        )
        db.session.add(inv_line)
    db.session.commit()
    return jsonify({'success': True, 'redirect': url_for('customer_invoices.view', invoice_id=invoice.id)})


@bp.route('/view/<token>')
def public_view(token):
    """Public invoice view page for customers - no login required"""
    from datetime import datetime
    invoice = CustomerInvoice.query.filter_by(view_token=token).first_or_404()

    # Check token hasn't expired
    if invoice.token_expires_at and datetime.utcnow() > invoice.token_expires_at:
        return render_template('customer_invoices/expired.html'), 410

    # Track the view
    if not invoice.viewed_at:
        invoice.viewed_at = datetime.utcnow()
        # Update status to viewed if still sent
        if invoice.status == 'sent':
            invoice.status = 'viewed'
    invoice.view_count = (invoice.view_count or 0) + 1
    db.session.commit()

    # Get the contractor (user) details
    from app.models.user import User
    contractor = User.query.get(invoice.user_id)

    return render_template('customer_invoices/public_view.html',
        invoice=invoice,
        contractor=contractor,
        token=token,
    )


@bp.route('/view/<token>/pdf')
def public_pdf(token):
    """Serve PDF for public invoice view"""
    from datetime import datetime
    invoice = CustomerInvoice.query.filter_by(view_token=token).first_or_404()

    if invoice.token_expires_at and datetime.utcnow() > invoice.token_expires_at:
        return "Link expired", 410

    from app.models.user import User
    contractor = User.query.get(invoice.user_id)
    from app.services.pdf_generator import generate_invoice_pdf
    pdf_bytes = generate_invoice_pdf(invoice, contractor)

    from flask import Response
    return Response(pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{invoice.invoice_number}.pdf"'}
    )
