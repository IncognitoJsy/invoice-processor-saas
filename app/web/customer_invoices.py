"""Customer Invoice routes - full platform mode"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
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
    invoices = CustomerInvoice.query.filter_by(user_id=current_user.id)\
        .order_by(CustomerInvoice.created_at.desc()).all()
    return render_template('customer_invoices/index.html', invoices=invoices)


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
    """Add a summary 'Materials Used' line"""
    materials_product = get_or_create_materials_used(current_user.id)
    total_selling = float(supplier_invoice.total_selling or 0)
    supplier_ref = supplier_invoice.supplier_name or 'Supplier'
    inv_num = supplier_invoice.invoice_number or ''
    description = f"Materials Used — {supplier_ref}" + (f" ({inv_num})" if inv_num else "")

    # Check if there's already a summary line from this supplier invoice
    existing = CustomerInvoiceLine.query.filter_by(
        customer_invoice_id=customer_invoice.id,
        source_invoice_id=supplier_invoice.id,
        line_type='summary'
    ).first()

    if existing:
        existing.unit_price = total_selling
        existing.line_total = total_selling
    else:
        line = CustomerInvoiceLine(
            customer_invoice_id=customer_invoice.id,
            source_invoice_id=supplier_invoice.id,
            product_service_id=materials_product.id,
            description=description,
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
