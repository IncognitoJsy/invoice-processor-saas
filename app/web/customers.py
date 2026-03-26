"""Customers routes - full platform mode"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.customer import Customer, Job
from datetime import datetime
import logging

bp = Blueprint('customers', __name__, url_prefix='/customers')


def _clean(val):
    """Strip whitespace and return None for empty or literal 'None' strings"""
    if val is None:
        return None
    val = str(val).strip()
    return None if val.lower() in ('none', '') else val
logger = logging.getLogger(__name__)


def require_full_mode(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.platform_mode not in ['full', 'both']:
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
@login_required
@require_full_mode
def index():
    customers = Customer.query.filter_by(user_id=current_user.id)\
        .order_by(Customer.name.asc()).all()
    return render_template('customers/index.html', customers=customers)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_full_mode
def new():
    if request.method == 'POST':
        customer = Customer(
            user_id=current_user.id,
            name=_clean(request.form.get('name', '')),
            company_name=_clean(request.form.get('company_name')),
            email=_clean(request.form.get('email')),
            phone=_clean(request.form.get('phone')),
            address_line1=_clean(request.form.get('address_line1')),
            address_line2=_clean(request.form.get('address_line2')),
            city=_clean(request.form.get('city')),
            postcode=_clean(request.form.get('postcode')),
            country=_clean(request.form.get('country')),
            notes=_clean(request.form.get('notes')),
            payment_terms=_clean(request.form.get('payment_terms')) or '30',
        )
        db.session.add(customer)
        db.session.commit()
        flash(f'Customer {customer.display_name} added successfully.', 'success')
        return redirect(url_for('customers.view', customer_id=customer.id))
    return render_template('customers/edit.html', customer=None)


@bp.route('/<int:customer_id>')
@login_required
@require_full_mode
def view(customer_id):
    from app.models.customer_invoice import CustomerInvoice
    customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first_or_404()
    invoices = CustomerInvoice.query.filter_by(
        customer_id=customer_id, user_id=current_user.id
    ).order_by(CustomerInvoice.created_at.desc()).all()
    from datetime import date as date_type
    today = date_type.today()

    # Categorise invoices
    unpaid = [i for i in invoices if i.status in ['open', 'sent', 'overdue']]
    sent_invoices = [i for i in invoices if i.status in ['sent', 'overdue']]
    overdue_invoices = [i for i in invoices if i.is_overdue]
    paid_invoices = [i for i in invoices if i.status == 'paid']

    from app.models.customer_payment import CustomerPayment
    payments = CustomerPayment.query.filter_by(
        user_id=current_user.id, customer_id=customer_id
    ).order_by(CustomerPayment.payment_date.desc()).all()

    from app.models.customer_quote import CustomerQuote
    quotes = CustomerQuote.query.filter_by(
        user_id=current_user.id, customer_id=customer_id
    ).order_by(CustomerQuote.created_at.desc()).all()

    total_open = sum(i.total or 0 for i in unpaid)
    total_sent = sum(i.total or 0 for i in sent_invoices)
    total_overdue = sum(i.total or 0 for i in overdue_invoices)
    total_paid = sum(i.total or 0 for i in paid_invoices)
    return render_template('customers/view.html',
        today=today,
        customer=customer,
        invoices=invoices,
        unpaid=unpaid,
        payments=payments,
        quotes=quotes,
        paid_invoices=paid_invoices,
        total_open=total_open,
        total_sent=total_sent,
        total_overdue=total_overdue,
        total_paid=total_paid,
    )


@bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
@require_full_mode
def edit(customer_id):
    customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        customer.name = _clean(request.form.get('name', ''))
        customer.company_name = _clean(request.form.get('company_name'))
        customer.email = _clean(request.form.get('email'))
        customer.phone = _clean(request.form.get('phone'))
        customer.address_line1 = _clean(request.form.get('address_line1'))
        customer.address_line2 = _clean(request.form.get('address_line2'))
        customer.city = _clean(request.form.get('city'))
        customer.postcode = _clean(request.form.get('postcode'))
        customer.country = _clean(request.form.get('country'))
        customer.payment_terms = _clean(request.form.get('payment_terms')) or '30'
        customer.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash('Customer updated successfully.', 'success')
        return redirect(url_for('customers.view', customer_id=customer.id))
    return render_template('customers/edit.html', customer=customer)


@bp.route('/<int:customer_id>/delete', methods=['POST'])
@login_required
@require_full_mode
def delete(customer_id):
    customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first_or_404()
    name = customer.display_name
    db.session.delete(customer)
    db.session.commit()
    flash(f'Customer {name} deleted.', 'success')
    return redirect(url_for('customers.index'))
