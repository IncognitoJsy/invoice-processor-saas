"""Bills & Purchases - full platform mode only"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.invoice import Invoice
from datetime import datetime, date, timedelta
from sqlalchemy import func

bp = Blueprint('bills', __name__, url_prefix='/bills')


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
    # Filters
    status_filter = request.args.get('status', 'all')
    supplier_filter = request.args.get('supplier', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    period = request.args.get('period', 'this_month')

    # Build query - only full platform invoices (processed supplier invoices + receipts)
    query = Invoice.query.filter_by(user_id=current_user.id)

    # Date range
    today = date.today()
    if period == 'this_month':
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'last_month':
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        date_from = last_month_end.replace(day=1).strftime('%Y-%m-%d')
        date_to = last_month_end.strftime('%Y-%m-%d')
    elif period == 'this_year':
        date_from = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif period == 'custom' and date_from and date_to:
        pass  # use provided dates
    else:
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')

    if date_from:
        try:
            query = query.filter(Invoice.processed_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Invoice.processed_at <= datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59))
        except ValueError:
            pass

    if status_filter != 'all':
        query = query.filter_by(bill_status=status_filter)

    if supplier_filter:
        query = query.filter(Invoice.supplier_name.ilike(f'%{supplier_filter}%'))

    bills = query.order_by(Invoice.processed_at.desc()).all()

    # Get unique suppliers for filter dropdown
    suppliers = db.session.query(Invoice.supplier_name).filter_by(
        user_id=current_user.id
    ).distinct().order_by(Invoice.supplier_name).all()
    suppliers = [s[0] for s in suppliers if s[0]]

    # Summary stats
    total_spent = sum(float(b.total_cost or 0) for b in bills)
    total_unpaid = sum(float(b.total_cost or 0) for b in bills if b.bill_status == 'unpaid')
    total_paid = sum(float(b.total_cost or 0) for b in bills if b.bill_status == 'paid')

    # Per supplier breakdown
    supplier_totals = {}
    for b in bills:
        sn = b.supplier_name or 'Unknown'
        if sn not in supplier_totals:
            supplier_totals[sn] = 0
        supplier_totals[sn] += float(b.total_cost or 0)
    supplier_totals = sorted(supplier_totals.items(), key=lambda x: x[1], reverse=True)

    return render_template('bills/index.html',
        bills=bills,
        suppliers=suppliers,
        status_filter=status_filter,
        supplier_filter=supplier_filter,
        period=period,
        date_from=date_from,
        date_to=date_to,
        total_spent=total_spent,
        total_unpaid=total_unpaid,
        total_paid=total_paid,
        supplier_totals=supplier_totals,
    )


@bp.route('/api/<int:bill_id>/mark-paid', methods=['POST'])
@login_required
@require_full_mode
def mark_paid(bill_id):
    bill = Invoice.query.filter_by(id=bill_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    bill.bill_status = 'paid'
    bill.bill_paid_at = datetime.strptime(data.get('paid_at', date.today().strftime('%Y-%m-%d')), '%Y-%m-%d').date()
    bill.bill_notes = data.get('notes', bill.bill_notes)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/<int:bill_id>/mark-unpaid', methods=['POST'])
@login_required
@require_full_mode
def mark_unpaid(bill_id):
    bill = Invoice.query.filter_by(id=bill_id, user_id=current_user.id).first_or_404()
    bill.bill_status = 'unpaid'
    bill.bill_paid_at = None
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/<int:bill_id>/mark-queried', methods=['POST'])
@login_required
@require_full_mode
def mark_queried(bill_id):
    bill = Invoice.query.filter_by(id=bill_id, user_id=current_user.id).first_or_404()
    bill.bill_status = 'queried'
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/<int:bill_id>/notes', methods=['POST'])
@login_required
@require_full_mode
def update_notes(bill_id):
    bill = Invoice.query.filter_by(id=bill_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    bill.bill_notes = data.get('notes', '')
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/upload-receipt', methods=['POST'])
@login_required
@require_full_mode
def upload_receipt():
    """Upload a receipt - AI extracts details"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    from app.web.upload import validate_upload, allowed_file
    error = validate_upload(file)
    if error:
        return jsonify({'error': error}), 400

    # Use existing parser to extract receipt data
    from app.parsers.parser_service import InvoiceParserService
    try:
        parser = InvoiceParserService()
        markup = current_user.default_markup or 0
        result = parser.parse_invoice(file, current_user.id, markup_percentage=markup)

        if result and result.get('success'):
            inv_id = result.get('invoice_id')
            if inv_id:
                inv = Invoice.query.get(inv_id)
                if inv:
                    inv.is_receipt = True
                    inv.bill_status = 'unpaid'
                    inv.document_type = 'receipt'
                    db.session.commit()
            return jsonify({'success': True, 'invoice_id': inv_id, 'message': 'Receipt processed successfully'})
        return jsonify({'error': 'Could not process receipt'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500
