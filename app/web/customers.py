"""Customers routes - full platform mode"""
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.customer import Customer, Job
from datetime import datetime
import logging

bp = Blueprint('customers', __name__, url_prefix='/customers')
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
            name=request.form.get('name', '').strip(),
            company_name=request.form.get('company_name', '').strip() or None,
            email=request.form.get('email', '').strip() or None,
            phone=request.form.get('phone', '').strip() or None,
            address_line1=request.form.get('address_line1', '').strip() or None,
            address_line2=request.form.get('address_line2', '').strip() or None,
            city=request.form.get('city', '').strip() or None,
            postcode=request.form.get('postcode', '').strip() or None,
            country=request.form.get('country', '').strip() or None,
            notes=request.form.get('notes', '').strip() or None,
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
    open_invoices = [i for i in invoices if i.status == 'open']
    outstanding = [i for i in invoices if i.status in ['sent', 'overdue']]
    paid_invoices = [i for i in invoices if i.status == 'paid']
    total_invoiced = sum(i.total or 0 for i in invoices if i.status != 'void')
    total_outstanding = sum(i.total or 0 for i in outstanding)
    total_paid = sum(i.total or 0 for i in paid_invoices)
    return render_template('customers/view.html',
        customer=customer,
        invoices=invoices,
        open_invoices=open_invoices,
        outstanding=outstanding,
        paid_invoices=paid_invoices,
        total_invoiced=total_invoiced,
        total_outstanding=total_outstanding,
        total_paid=total_paid,
    )


@bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
@require_full_mode
def edit(customer_id):
    customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        customer.name = request.form.get('name', '').strip()
        customer.company_name = request.form.get('company_name', '').strip() or None
        customer.email = request.form.get('email', '').strip() or None
        customer.phone = request.form.get('phone', '').strip() or None
        customer.address_line1 = request.form.get('address_line1', '').strip() or None
        customer.address_line2 = request.form.get('address_line2', '').strip() or None
        customer.city = request.form.get('city', '').strip() or None
        customer.postcode = request.form.get('postcode', '').strip() or None
        customer.country = request.form.get('country', '').strip() or None
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
