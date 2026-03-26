"""Customer Payments routes"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.customer_payment import CustomerPayment, CustomerInvoicePayment
from app.models.customer_invoice import CustomerInvoice
from app.models.customer import Customer
from datetime import datetime, date

bp = Blueprint('customer_payments', __name__, url_prefix='/customer-payments')


def require_full_mode(f):
    from functools import wraps
    from flask import abort
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.platform_mode not in ('full', 'both'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
@login_required
@require_full_mode
def index():
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    customer_id = request.args.get('customer_id', type=int)
    selected_customer = None
    open_invoices = []

    if customer_id:
        selected_customer = Customer.query.filter_by(
            id=customer_id, user_id=current_user.id).first()
        if selected_customer:
            open_invoices = CustomerInvoice.query.filter(
                CustomerInvoice.user_id == current_user.id,
                CustomerInvoice.customer_id == customer_id,
                CustomerInvoice.status.in_(['open', 'sent', 'overdue'])
            ).order_by(CustomerInvoice.due_date).all()

    return render_template('customer_payments/index.html',
        customers=customers,
        selected_customer=selected_customer,
        open_invoices=open_invoices,
        payment_methods=CustomerPayment.PAYMENT_METHODS,
        today=date.today().strftime('%Y-%m-%d'),
    )


@bp.route('/record', methods=['POST'])
@login_required
@require_full_mode
def record():
    data = request.get_json()
    customer_id = data.get('customer_id')
    invoice_ids = data.get('invoice_ids', [])
    amount = float(data.get('amount', 0))
    payment_date_str = data.get('payment_date')
    payment_method = data.get('payment_method', 'bank_transfer')
    reference = data.get('reference', '')
    notes = data.get('notes', '')

    if not customer_id or not invoice_ids or amount <= 0:
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        payment_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        payment_date = date.today()

    # Verify all invoices belong to this user and customer
    invoices = CustomerInvoice.query.filter(
        CustomerInvoice.id.in_(invoice_ids),
        CustomerInvoice.user_id == current_user.id,
        CustomerInvoice.customer_id == customer_id
    ).all()

    if not invoices:
        return jsonify({'error': 'No valid invoices found'}), 400

    # Create payment record
    payment = CustomerPayment(
        user_id=current_user.id,
        customer_id=customer_id,
        amount=amount,
        payment_date=payment_date,
        payment_method=payment_method,
        reference=reference or None,
        notes=notes or None,
    )
    db.session.add(payment)
    db.session.flush()

    # Link payment to each invoice and mark as paid
    remaining = amount
    for invoice in invoices:
        applied = min(remaining, invoice.total or 0)
        link = CustomerInvoicePayment(
            payment_id=payment.id,
            invoice_id=invoice.id,
            amount_applied=applied
        )
        db.session.add(link)
        invoice.status = 'paid'
        invoice.paid_at = datetime.utcnow()
        remaining -= applied
        if remaining <= 0:
            break

    db.session.commit()

    return jsonify({
        'success': True,
        'payment_id': payment.id,
        'invoices_paid': len(invoices),
        'redirect': url_for('customer_invoices.index', tab='paid')
    })


@bp.route('/history/<int:customer_id>')
@login_required
@require_full_mode
def history(customer_id):
    """Get interleaved invoice + payment history for a customer"""
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()

    invoices = CustomerInvoice.query.filter_by(
        user_id=current_user.id, customer_id=customer_id
    ).order_by(CustomerInvoice.issue_date.desc()).all()

    payments = CustomerPayment.query.filter_by(
        user_id=current_user.id, customer_id=customer_id
    ).order_by(CustomerPayment.payment_date.desc()).all()

    # Interleave into timeline
    timeline = []
    for inv in invoices:
        timeline.append({
            'type': 'invoice',
            'date': inv.issue_date,
            'number': inv.invoice_number,
            'amount': inv.total,
            'status': inv.status,
            'id': inv.id,
        })
    for pay in payments:
        timeline.append({
            'type': 'payment',
            'date': pay.payment_date,
            'method': pay.method_label,
            'amount': pay.amount,
            'reference': pay.reference,
            'id': pay.id,
        })

    timeline.sort(key=lambda x: x['date'] or date.today(), reverse=True)

    return render_template('customer_payments/history.html',
        customer=customer,
        timeline=timeline,
    )
