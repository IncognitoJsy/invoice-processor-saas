"""Dashboard routes"""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@bp.route('/')
@login_required
def index():
    if not current_user.setup_completed:
        return redirect(url_for('setup.index'))

    from app.models.invoice import Invoice
    from app.models.quickbooks import QuickBooksConnection
    from app.models.xero import XeroConnection

    first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_invoices = Invoice.query.filter_by(user_id=current_user.id).count()
    invoices_this_month = Invoice.query.filter(
        Invoice.user_id == current_user.id,
        Invoice.created_at >= first_of_month
    ).count()

    recent_invoices = Invoice.query.filter_by(user_id=current_user.id)\
        .order_by(Invoice.created_at.desc())\
        .limit(5).all()

    qb_connection = QuickBooksConnection.query.filter_by(user_id=current_user.id).first()
    qb_connected = qb_connection and qb_connection.is_active if qb_connection else False

    xero_connection = XeroConnection.query.filter_by(user_id=current_user.id).first()
    xero_connected = xero_connection and xero_connection.is_active if xero_connection else False

    limit = current_user.monthly_invoice_limit
    if limit == float('inf'):
        limit_display = 'Unlimited'
        usage_percent = 0
    else:
        limit_display = str(int(limit))
        usage_percent = min(100, int((invoices_this_month / limit) * 100)) if limit > 0 else 100

    mode = current_user.platform_mode or 'sync'

    return render_template('dashboard/index.html',
        total_invoices=total_invoices,
        invoices_this_month=invoices_this_month,
        invoice_limit=limit_display,
        usage_percent=usage_percent,
        recent_invoices=recent_invoices,
        qb_connected=qb_connected,
        xero_connected=xero_connected,
        platform_mode=mode,
    )
