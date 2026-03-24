"""Tax reporting routes for GoZappify
Provides VAT/GST return summaries for tax-registered users
"""
from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models.invoice import Invoice
from app.models.customer_invoice import CustomerInvoice
from datetime import datetime, date
import csv
import io

bp = Blueprint('tax_reports', __name__, url_prefix='/tax-reports')


def require_tax_registered(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.tax_registered:
            return render_template('tax_reports/not_registered.html')
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
@login_required
@require_tax_registered
def index():
    # Default to current quarter
    today = date.today()
    quarter_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    
    date_from = request.args.get('from', quarter_start.strftime('%Y-%m-%d'))
    date_to = request.args.get('to', today.strftime('%Y-%m-%d'))
    period = request.args.get('period', 'custom')

    # Handle period shortcuts
    if period == 'month':
        date_from = date(today.year, today.month, 1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'quarter':
        date_from = quarter_start.strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'year':
        date_from = date(today.year, 1, 1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'last_quarter':
        lq_end_month = ((today.month - 1) // 3) * 3
        if lq_end_month == 0:
            lq_end_month = 12
            lq_year = today.year - 1
        else:
            lq_year = today.year
        lq_start_month = lq_end_month - 2
        date_from = date(lq_year, lq_start_month, 1).strftime('%Y-%m-%d')
        import calendar
        date_to = date(lq_year, lq_end_month,
                      calendar.monthrange(lq_year, lq_end_month)[1]).strftime('%Y-%m-%d')

    try:
        dt_from = datetime.strptime(date_from, '%Y-%m-%d')
        dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        dt_from = datetime.combine(quarter_start, datetime.min.time())
        dt_to = datetime.combine(today, datetime.max.time())

    tax_type = current_user.tax_type or 'VAT'

    # Input tax — VAT/GST paid to suppliers on processed invoices
    supplier_invoices = Invoice.query.filter(
        Invoice.user_id == current_user.id,
        Invoice.processed_at >= dt_from,
        Invoice.processed_at <= dt_to,
        Invoice.status == 'completed'
    ).order_by(Invoice.processed_at.desc()).all()

    input_tax_total = sum(inv.supplier_tax_amount or 0 for inv in supplier_invoices)
    input_net_total = sum(inv.total_ex_tax or inv.total_cost or 0 for inv in supplier_invoices)

    # Output tax — VAT/GST collected from customers on PAID customer invoices
    customer_invoices = CustomerInvoice.query.filter(
        CustomerInvoice.user_id == current_user.id,
        CustomerInvoice.status == 'paid',
        CustomerInvoice.paid_at >= dt_from,
        CustomerInvoice.paid_at <= dt_to,
        CustomerInvoice.tax_rate > 0
    ).order_by(CustomerInvoice.paid_at.desc()).all()

    output_tax_total = sum(inv.tax_amount or 0 for inv in customer_invoices)
    output_net_total = sum(inv.subtotal or 0 for inv in customer_invoices)
    output_gross_total = sum(inv.total or 0 for inv in customer_invoices)

    net_tax = round(output_tax_total - input_tax_total, 2)

    return render_template('tax_reports/index.html',
        tax_type=tax_type,
        date_from=date_from,
        date_to=date_to,
        period=period,
        supplier_invoices=supplier_invoices,
        customer_invoices=customer_invoices,
        input_tax_total=round(input_tax_total, 2),
        input_net_total=round(input_net_total, 2),
        output_tax_total=round(output_tax_total, 2),
        output_net_total=round(output_net_total, 2),
        output_gross_total=round(output_gross_total, 2),
        net_tax=net_tax,
    )


@bp.route('/export')
@login_required
@require_tax_registered
def export_csv():
    """Export tax report as CSV"""
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')
    report_type = request.args.get('type', 'both')  # input, output, both
    tax_type = current_user.tax_type or 'VAT'

    try:
        dt_from = datetime.strptime(date_from, '%Y-%m-%d')
        dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        dt_from = datetime(2020, 1, 1)
        dt_to = datetime.utcnow()

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type in ('input', 'both'):
        writer.writerow([f'Input {tax_type} (Supplier Invoices)'])
        writer.writerow(['Date', 'Supplier', 'Invoice No', 'Net Amount', f'{tax_type} Amount', 'Gross Amount'])
        supplier_invoices = Invoice.query.filter(
            Invoice.user_id == current_user.id,
            Invoice.processed_at >= dt_from,
            Invoice.processed_at <= dt_to,
            Invoice.status == 'completed'
        ).all()
        for inv in supplier_invoices:
            writer.writerow([
                inv.processed_at.strftime('%d/%m/%Y') if inv.processed_at else '',
                inv.supplier_name or '',
                inv.invoice_number or '',
                f'{inv.total_ex_tax or inv.total_cost or 0:.2f}',
                f'{inv.supplier_tax_amount or 0:.2f}',
                f'{inv.total_inc_tax or inv.total_cost or 0:.2f}',
            ])
        input_tax = sum(inv.supplier_tax_amount or 0 for inv in supplier_invoices)
        writer.writerow(['', '', 'TOTAL', '', f'{input_tax:.2f}', ''])
        writer.writerow([])

    if report_type in ('output', 'both'):
        writer.writerow([f'Output {tax_type} (Customer Invoices - Paid)'])
        writer.writerow(['Date Paid', 'Customer', 'Invoice No', 'Net Amount', f'{tax_type} Amount', 'Gross Amount'])
        customer_invoices = CustomerInvoice.query.filter(
            CustomerInvoice.user_id == current_user.id,
            CustomerInvoice.status == 'paid',
            CustomerInvoice.paid_at >= dt_from,
            CustomerInvoice.paid_at <= dt_to,
        ).all()
        for inv in customer_invoices:
            writer.writerow([
                inv.paid_at.strftime('%d/%m/%Y') if inv.paid_at else '',
                inv.customer.display_name if inv.customer else '',
                inv.invoice_number or '',
                f'{inv.subtotal or 0:.2f}',
                f'{inv.tax_amount or 0:.2f}',
                f'{inv.total or 0:.2f}',
            ])
        output_tax = sum(inv.tax_amount or 0 for inv in customer_invoices)
        writer.writerow(['', '', 'TOTAL', '', f'{output_tax:.2f}', ''])

    csv_content = output.getvalue()
    filename = f'tax_report_{date_from}_to_{date_to}.csv'

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )
