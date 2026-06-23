"""Reports - P&L, VAT, exports"""
from flask import Blueprint, render_template, request, jsonify, make_response
from flask_login import login_required, current_user
from app.extensions import db
from app.utils.money import money, to_decimal
from sqlalchemy import text
from datetime import datetime, date, timedelta
import csv
import io

bp = Blueprint('reports', __name__, url_prefix='/reports')


@bp.route('/')
@login_required
def index():
    return render_template('reports/index.html')


@bp.route('/api/pnl')
@login_required
def api_pnl():
    """P&L based on payment received date (cash accounting)"""
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    period = request.args.get('period', 'this_month')

    today = date.today()
    if period == 'this_month':
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        date_from = last_month_end.replace(day=1).strftime('%Y-%m-%d')
        date_to = last_month_end.strftime('%Y-%m-%d')
    elif period == 'this_quarter':
        quarter = (today.month - 1) // 3
        date_from = date(today.year, quarter * 3 + 1, 1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'this_year':
        date_from = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'last_year':
        date_from = date(today.year - 1, 1, 1).strftime('%Y-%m-%d')
        date_to = date(today.year - 1, 12, 31).strftime('%Y-%m-%d')

    try:
        df = datetime.strptime(date_from, '%Y-%m-%d')
        dt = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59)
    except:
        return jsonify({'error': 'Invalid dates'}), 400

    # Revenue — invoices paid within date range (payment date, not invoice date)
    revenue_rows = db.session.execute(text("""
        SELECT 
            ci.invoice_number,
            ci.issue_date,
            ci.paid_at,
            ci.total,
            ci.tax_amount,
            c.name as customer_name
        FROM customer_invoice ci
        LEFT JOIN customer c ON ci.customer_id = c.id
        WHERE ci.user_id = :uid
        AND ci.status = 'paid'
        AND ci.paid_at >= :df
        AND ci.paid_at <= :dt
        ORDER BY ci.paid_at DESC
    """), {'uid': current_user.id, 'df': df, 'dt': dt}).fetchall()

    # Costs — supplier invoices processed in date range
    cost_rows = db.session.execute(text("""
        SELECT 
            invoice_number,
            invoice_date,
            processed_at,
            total_cost,
            supplier_name
        FROM invoice
        WHERE user_id = :uid
        AND status = 'completed'
        AND processed_at >= :df
        AND processed_at <= :dt
        ORDER BY processed_at DESC
    """), {'uid': current_user.id, 'df': df, 'dt': dt}).fetchall()

    # Decimal end-to-end; money() rounds, float() only at the JSON edge below.
    total_revenue = money(sum((to_decimal(r.total or 0) for r in revenue_rows), to_decimal(0)))
    total_vat_collected = money(sum((to_decimal(r.tax_amount or 0) for r in revenue_rows), to_decimal(0)))
    total_revenue_ex_vat = money(total_revenue - total_vat_collected)
    total_costs = money(sum((to_decimal(r.total_cost or 0) for r in cost_rows), to_decimal(0)))
    gross_profit = money(total_revenue_ex_vat - total_costs)
    margin = (money(gross_profit / total_revenue_ex_vat * 100, places=1)
              if total_revenue_ex_vat > 0 else to_decimal(0))

    # Monthly breakdown (Decimal; converted to float at the return edge)
    monthly = {}
    for r in revenue_rows:
        if r.paid_at:
            key = r.paid_at.strftime('%b %Y')
            if key not in monthly:
                monthly[key] = {'revenue': to_decimal(0), 'costs': to_decimal(0)}
            monthly[key]['revenue'] += to_decimal(r.total or 0)
    for r in cost_rows:
        if r.processed_at:
            key = r.processed_at.strftime('%b %Y')
            if key not in monthly:
                monthly[key] = {'revenue': to_decimal(0), 'costs': to_decimal(0)}
            monthly[key]['costs'] += to_decimal(r.total_cost or 0)

    return jsonify({
        'period': {'from': date_from, 'to': date_to},
        'summary': {
            'total_revenue': float(total_revenue),
            'total_revenue_ex_vat': float(total_revenue_ex_vat),
            'total_vat_collected': float(total_vat_collected),
            'total_costs': float(total_costs),
            'gross_profit': float(gross_profit),
            'margin_pct': float(margin),
            'invoice_count': len(revenue_rows),
            'cost_count': len(cost_rows),
        },
        'revenue_items': [{
            'invoice_number': r.invoice_number,
            'customer': r.customer_name or '—',
            'issue_date': r.issue_date.strftime('%d %b %Y') if r.issue_date else '—',
            'paid_date': r.paid_at.strftime('%d %b %Y') if r.paid_at else '—',
            'total': float(money(r.total or 0)),
            'vat': float(money(r.tax_amount or 0)),
        } for r in revenue_rows],
        'cost_items': [{
            'supplier': r.supplier_name,
            'invoice_number': r.invoice_number or '—',
            'date': r.invoice_date.strftime('%d %b %Y') if r.invoice_date else '—',
            'total': float(money(r.total_cost or 0)),
        } for r in cost_rows],
        'monthly': {k: {'revenue': float(money(v['revenue'])), 'costs': float(money(v['costs']))}
                    for k, v in monthly.items()},
    })


@bp.route('/api/vat')
@login_required
def api_vat():
    """VAT/GST return summary for a quarter"""
    # Unified on tax_registered (the canonical 'registered' flag the resolver/parser use);
    # legacy vat_registered is retired. NOTE: this /api/vat surface duplicates tax_reports.py —
    # whether to retire it is a separate cleanup decision, out of scope here.
    if not current_user.tax_registered:
        return jsonify({'error': 'Not tax registered'}), 400

    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    try:
        df = datetime.strptime(date_from, '%Y-%m-%d')
        dt = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59)
    except:
        return jsonify({'error': 'Invalid dates'}), 400

    # VAT on sales (output tax) — paid invoices
    sales = db.session.execute(text("""
        SELECT SUM(total) as gross, SUM(tax_amount) as vat, SUM(subtotal) as net
        FROM customer_invoice
        WHERE user_id = :uid AND status = 'paid'
        AND paid_at >= :df AND paid_at <= :dt
    """), {'uid': current_user.id, 'df': df, 'dt': dt}).fetchone()

    # VAT on purchases (input tax) — supplier invoices
    purchases = db.session.execute(text("""
        SELECT SUM(total_cost) as net
        FROM invoice
        WHERE user_id = :uid AND status = 'completed'
        AND processed_at >= :df AND processed_at <= :dt
    """), {'uid': current_user.id, 'df': df, 'dt': dt}).fetchone()

    output_vat = money(sales.vat or 0)
    # Input-tax estimate uses the canonical tax_rate (vat_rate retired with the vat_* unification).
    input_vat_estimate = money(to_decimal(purchases.net or 0) * to_decimal(current_user.tax_rate or 0) / 100)
    vat_due = money(output_vat - input_vat_estimate)

    return jsonify({
        'period': {'from': date_from, 'to': date_to},
        'box1_vat_due_sales': float(output_vat),
        'box4_vat_reclaimed': float(input_vat_estimate),
        'box5_net_vat_due': float(vat_due),
        'box6_total_sales_ex_vat': float(money(sales.net or 0)),
        'box7_total_purchases_ex_vat': float(money(purchases.net or 0)),
        'note': 'Input VAT is estimated. Confirm with your accountant.'
    })


@bp.route('/api/export/invoices')
@login_required
def export_invoices():
    """CSV export of all invoices"""
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    query = """
        SELECT ci.invoice_number, c.name as customer, ci.issue_date, ci.due_date,
               ci.paid_at, ci.status, ci.subtotal, ci.tax_amount, ci.total,
               ci.void_reason
        FROM customer_invoice ci
        LEFT JOIN customer c ON ci.customer_id = c.id
        WHERE ci.user_id = :uid
    """
    params = {'uid': current_user.id}

    if date_from:
        query += " AND ci.issue_date >= :df"
        params['df'] = date_from
    if date_to:
        query += " AND ci.issue_date <= :dt"
        params['dt'] = date_to

    query += " ORDER BY ci.issue_date DESC"
    rows = db.session.execute(text(query), params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Invoice Number', 'Customer', 'Issue Date', 'Due Date',
                     'Paid Date', 'Status', 'Subtotal', 'VAT', 'Total', 'Void Reason'])
    for r in rows:
        writer.writerow([
            r.invoice_number, r.customer,
            r.issue_date.strftime('%d/%m/%Y') if r.issue_date else '',
            r.due_date.strftime('%d/%m/%Y') if r.due_date else '',
            r.paid_at.strftime('%d/%m/%Y') if r.paid_at else '',
            r.status, f'{r.subtotal:.2f}', f'{(r.tax_amount or 0):.2f}',
            f'{r.total:.2f}', r.void_reason or ''
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=invoices_{date.today()}.csv'
    return response


@bp.route('/api/export/supplier-invoices')
@login_required
def export_supplier_invoices():
    """CSV export of supplier invoices"""
    rows = db.session.execute(text("""
        SELECT supplier_name, invoice_number, invoice_date, processed_at,
               total_cost, total_selling, total_profit, status
        FROM invoice
        WHERE user_id = :uid AND status = 'completed'
        ORDER BY processed_at DESC
    """), {'uid': current_user.id}).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Supplier', 'Invoice Number', 'Invoice Date', 'Processed Date',
                     'Cost', 'Selling Price', 'Profit', 'Status'])
    for r in rows:
        writer.writerow([
            r.supplier_name, r.invoice_number or '',
            r.invoice_date.strftime('%d/%m/%Y') if r.invoice_date else '',
            r.processed_at.strftime('%d/%m/%Y') if r.processed_at else '',
            f'{(r.total_cost or 0):.2f}', f'{(r.total_selling or 0):.2f}',
            f'{(r.total_profit or 0):.2f}', r.status
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename=supplier_invoices_{date.today()}.csv'
    return response
