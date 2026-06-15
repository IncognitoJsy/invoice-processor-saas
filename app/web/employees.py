"""Employee routes - full platform only"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.employee import Employee, LabourEntry
from datetime import datetime, date

bp = Blueprint('employees', __name__, url_prefix='/employees')


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
    employees = Employee.query.filter_by(
        user_id=current_user.id
    ).order_by(Employee.name).all()
    contribution_rate = float(current_user.employer_contribution_rate or 6.5)
    return render_template('employees/index.html',
        employees=employees,
        contribution_rate=contribution_rate,
    )


@bp.route('/create', methods=['POST'])
@login_required
@require_full_mode
def create():
    data = request.get_json()
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    emp = Employee(
        user_id=current_user.id,
        name=name,
        role=data.get('role', '').strip() or None,
        mobile=data.get('mobile', '').strip() or None,
        email=data.get('email', '').strip() or None,
        pay_rate=float(data.get('pay_rate') or 0),
        charge_out_rate=float(data.get('charge_out_rate') or 0),
        notes=data.get('notes', '').strip() or None,
    )
    db.session.add(emp)
    db.session.commit()
    return jsonify({'success': True, 'employee': emp.to_dict(float(current_user.employer_contribution_rate or 6.5))})


@bp.route('/<int:emp_id>', methods=['GET'])
@login_required
@require_full_mode
def get(emp_id):
    emp = Employee.query.filter_by(id=emp_id, user_id=current_user.id).first_or_404()
    return jsonify(emp.to_dict(float(current_user.employer_contribution_rate or 6.5)))


@bp.route('/<int:emp_id>/update', methods=['POST'])
@login_required
@require_full_mode
def update(emp_id):
    emp = Employee.query.filter_by(id=emp_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    emp.name = data.get('name', emp.name).strip()
    emp.role = data.get('role', emp.role or '').strip() or None
    emp.mobile = data.get('mobile', emp.mobile or '').strip() or None
    emp.email = data.get('email', emp.email or '').strip() or None
    emp.pay_rate = float(data.get('pay_rate') or emp.pay_rate)
    emp.charge_out_rate = float(data.get('charge_out_rate') or emp.charge_out_rate)
    emp.notes = data.get('notes', emp.notes or '').strip() or None
    emp.is_active = data.get('is_active', emp.is_active)
    db.session.commit()
    return jsonify({'success': True, 'employee': emp.to_dict(float(current_user.employer_contribution_rate or 6.5))})


@bp.route('/<int:emp_id>/deactivate', methods=['POST'])
@login_required
@require_full_mode
def deactivate(emp_id):
    emp = Employee.query.filter_by(id=emp_id, user_id=current_user.id).first_or_404()
    emp.is_active = False
    db.session.commit()
    return jsonify({'success': True})


# ─── Labour Entry Routes ───────────────────────────────────────

@bp.route('/labour/log', methods=['POST'])
@login_required
@require_full_mode
def log_labour():
    """Log hours for an employee against a job card"""
    data = request.get_json()
    emp_id = data.get('employee_id')
    hours = float(data.get('hours') or 0)
    if not emp_id or hours <= 0:
        return jsonify({'error': 'Employee and hours required'}), 400

    emp = Employee.query.filter_by(id=emp_id, user_id=current_user.id).first_or_404()
    contribution_rate = float(current_user.employer_contribution_rate or 6.5)

    # Tenant isolation (AUDIT risk #6): any job_card_id / customer_id supplied
    # by the client must belong to the current user. Look them up scoped by
    # user_id and 404 on a foreign/missing id rather than linking the labour
    # entry to another tenant's job card or customer.
    job_card_id = data.get('job_card_id') or None
    customer_id = data.get('customer_id') or None
    if job_card_id:
        from app.models.job_card import JobCard
        job = JobCard.query.filter_by(id=job_card_id, user_id=current_user.id).first_or_404()
        if not customer_id:
            customer_id = job.customer_id
    if customer_id:
        from app.models.customer import Customer
        Customer.query.filter_by(id=customer_id, user_id=current_user.id).first_or_404()

    entry = LabourEntry(
        user_id=current_user.id,
        employee_id=emp_id,
        job_card_id=job_card_id,
        customer_id=customer_id,
        hours=hours,
        charge_out_rate=float(emp.charge_out_rate),
        pay_rate=float(emp.pay_rate),
        employer_contribution_rate=contribution_rate,
        date_worked=datetime.strptime(data['date_worked'], '%Y-%m-%d').date() if data.get('date_worked') else date.today(),
        time_worked=datetime.strptime(data['time_worked'], '%H:%M').time() if data.get('time_worked') else datetime.now().time().replace(second=0, microsecond=0),
        description=data.get('description', '').strip() or None,
        status='logged',
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify({'success': True, 'entry': entry.to_dict()})


@bp.route('/labour/<int:entry_id>/delete', methods=['POST'])
@login_required
@require_full_mode
def delete_labour(entry_id):
    entry = LabourEntry.query.filter_by(id=entry_id, user_id=current_user.id).first_or_404()
    if entry.status == 'invoiced':
        return jsonify({'error': 'Cannot delete invoiced labour entry'}), 400
    db.session.delete(entry)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/job/<int:job_card_id>/labour')
@login_required
@require_full_mode
def api_job_labour(job_card_id):
    """Get all labour entries for a job card"""
    entries = LabourEntry.query.filter_by(
        user_id=current_user.id,
        job_card_id=job_card_id
    ).order_by(LabourEntry.date_worked.desc()).all()
    return jsonify({'entries': [e.to_dict() for e in entries]})


@bp.route('/api/job/<int:job_card_id>/labour/uninvoiced')
@login_required
@require_full_mode
def api_job_labour_uninvoiced(job_card_id):
    """Get uninvoiced labour entries for a job — used when adding to invoice"""
    entries = LabourEntry.query.filter_by(
        user_id=current_user.id,
        job_card_id=job_card_id,
        status='logged'
    ).order_by(LabourEntry.date_worked.desc()).all()
    return jsonify({'entries': [e.to_dict() for e in entries]})


@bp.route('/api/add-to-invoice', methods=['POST'])
@login_required
@require_full_mode
def add_to_invoice():
    """Add labour entries to invoice - auto-creates if none exists, merges same employee"""
    from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
    from datetime import date as date_type, datetime as dt_type, time as time_type, timedelta

    data = request.get_json()
    invoice_id = data.get('invoice_id')
    entry_ids = data.get('entry_ids', [])
    cutoff_date = data.get('cutoff_date')
    cutoff_time_str = data.get('cutoff_time', '23:59')
    customer_id = data.get('customer_id')
    job_card_id = data.get('job_card_id')

    # Determine cutoff datetime
    try:
        cutoff_d = date_type.fromisoformat(cutoff_date) if cutoff_date else date_type.today()
        cutoff_t = dt_type.strptime(cutoff_time_str, '%H:%M').time()
        cutoff_dt = dt_type.combine(cutoff_d, cutoff_t)
    except:
        cutoff_dt = dt_type.now()
    cutoff = cutoff_dt.date()

    # Auto-create invoice if none provided
    if not invoice_id:
        # Get customer_id from job card if needed
        if not customer_id and job_card_id:
            from app.models.job_card import JobCard
            job = JobCard.query.filter_by(id=job_card_id, user_id=current_user.id).first()
            if job:
                customer_id = job.customer_id

        if not customer_id:
            return jsonify({'error': 'Customer required to create invoice'}), 400

        # Check for existing open invoice
        existing = CustomerInvoice.query.filter(
            CustomerInvoice.user_id == current_user.id,
            CustomerInvoice.customer_id == customer_id,
            CustomerInvoice.status.in_(['open', 'draft'])
        ).order_by(CustomerInvoice.created_at.desc()).first()

        if existing:
            invoice = existing
            invoice_id = existing.id
        else:
            user = current_user
            next_num = user.next_invoice_number or 1
            prefix = user.invoice_prefix or 'INV'
            inv_number = f"{prefix}-{next_num:03d}"
            user.next_invoice_number = next_num + 1
            try:
                terms_days = int(user.default_payment_terms or 30)
            except:
                terms_days = 30
            today = date_type.today()
            invoice = CustomerInvoice(
                user_id=current_user.id,
                customer_id=customer_id,
                job_card_id=job_card_id,
                invoice_number=inv_number,
                status='open',
                issue_date=today,
                due_date=today + timedelta(days=terms_days),
                payment_terms=str(terms_days),
                subtotal=0, tax_rate=0, tax_amount=0, total=0,
            )
            db.session.add(invoice)
            db.session.flush()
            invoice_id = invoice.id
    else:
        invoice = CustomerInvoice.query.filter_by(
            id=invoice_id, user_id=current_user.id).first()
        if not invoice:
            return jsonify({'error': 'Invoice not found'}), 404

    # If no entry_ids given, find all pending for this job/customer up to cutoff
    if not entry_ids:
        from sqlalchemy import or_
        filters = [LabourEntry.user_id == current_user.id, LabourEntry.status == 'logged']
        if invoice.job_card_id:
            filters.append(LabourEntry.job_card_id == invoice.job_card_id)
        elif invoice.customer_id:
            from app.models.job_card import JobCard
            job_ids = [j.id for j in JobCard.query.filter_by(
                user_id=current_user.id, customer_id=invoice.customer_id).all()]
            conds = [LabourEntry.customer_id == invoice.customer_id]
            if job_ids:
                conds.append(LabourEntry.job_card_id.in_(job_ids))
            filters.append(or_(*conds))
        pending = LabourEntry.query.filter(*filters).all()
        entry_ids = [e.id for e in pending
                    if not e.date_worked or e.date_worked <= cutoff]

    # Build lookup of existing labour lines by employee name
    existing_lines = {}
    for line in CustomerInvoiceLine.query.filter_by(
            customer_invoice_id=invoice_id, line_type='labour').all():
        key = line.description.split(' — ')[0].strip()
        existing_lines[key] = line

    added = 0
    skipped_future = 0

    for entry_id in entry_ids:
        entry = LabourEntry.query.filter_by(
            id=entry_id, user_id=current_user.id).first()
        if not entry or entry.status == 'invoiced':
            continue

        # Skip future hours
        if entry.date_worked:
            entry_time = entry.time_worked if entry.time_worked else time_type(9, 0)
            entry_dt = dt_type.combine(entry.date_worked, entry_time)
            if entry_dt > cutoff_dt:
                skipped_future += 1
                continue

        emp = entry.employee
        emp_key = emp.display_name if emp else 'Labour'
        hours = float(entry.hours or 0)
        rate = float(entry.charge_out_rate or 0)

        if emp_key in existing_lines:
            line = existing_lines[emp_key]
            line.quantity = float(line.quantity or 0) + hours
            if rate > float(line.unit_price or 0):
                line.unit_price = rate
            line.line_total = float(line.quantity) * float(line.unit_price)
        else:
            desc = f"{emp_key} — Billable time"
            sort_order = CustomerInvoiceLine.query.filter_by(
                customer_invoice_id=invoice_id).count()
            line = CustomerInvoiceLine(
                customer_invoice_id=invoice_id,
                description=desc,
                quantity=hours,
                unit_price=rate,
                line_total=hours * rate,
                line_type='labour',
                sort_order=sort_order,
            )
            db.session.add(line)
            db.session.flush()
            existing_lines[emp_key] = line

        entry.status = 'invoiced'
        entry.customer_invoice_id = invoice_id
        added += 1

    if added:
        invoice.recalculate_totals()

    db.session.commit()

    msg = f'{added} hour {"entries" if added != 1 else "entry"} added to invoice {invoice.invoice_number}'
    if skipped_future:
        msg += f' ({skipped_future} future entries kept pending)'

    return jsonify({
        'success': True,
        'added': added,
        'skipped_future': skipped_future,
        'message': msg,
        'invoice_id': invoice_id,
        'invoice_number': invoice.invoice_number,
        'invoice_total': float(invoice.total or 0),
    })


@bp.route('/api/list')
@login_required
@require_full_mode
def api_list():
    """Get all active employees — for dropdowns"""
    employees = Employee.query.filter_by(
        user_id=current_user.id, is_active=True
    ).order_by(Employee.name).all()
    rate = float(current_user.employer_contribution_rate or 6.5)
    return jsonify({'employees': [e.to_dict(rate) for e in employees]})


@bp.route('/api/customer/<int:customer_id>/labour')
@login_required
@require_full_mode
def api_customer_labour(customer_id):
    """Get all labour entries for a customer"""
    from app.models.job_card import JobCard
    from sqlalchemy import or_

    job_ids = [j.id for j in JobCard.query.filter_by(
        user_id=current_user.id, customer_id=customer_id).all()]

    filters = [LabourEntry.customer_id == customer_id]
    if job_ids:
        filters.append(LabourEntry.job_card_id.in_(job_ids))

    entries = LabourEntry.query.filter(
        LabourEntry.user_id == current_user.id,
        or_(*filters)
    ).order_by(LabourEntry.date_worked.desc()).all()

    return jsonify({'entries': [e.to_dict() for e in entries]})


@bp.route('/api/preview-hours', methods=['POST'])
@login_required
@require_full_mode
def preview_hours():
    """Preview which hours will be added based on cutoff datetime"""
    from datetime import datetime as dt_type, time as time_type, date as date_type
    from app.models.customer_invoice import CustomerInvoice
    from sqlalchemy import or_

    data = request.get_json()
    invoice_id = data.get('invoice_id')
    cutoff_date = data.get('cutoff_date')
    cutoff_time = data.get('cutoff_time', '23:59')

    from app.models.user import User
    from datetime import date as dt_date, timedelta

    # Auto-create invoice if none provided
    if not invoice_id:
        # Need customer_id to create
        customer_id_for_create = data.get('customer_id')
        job_card_id_for_create = data.get('job_card_id')

        if not customer_id_for_create and job_card_id_for_create:
            from app.models.job_card import JobCard
            job = JobCard.query.filter_by(
                id=job_card_id_for_create, user_id=current_user.id).first()
            if job:
                customer_id_for_create = job.customer_id

        if not customer_id_for_create:
            return jsonify({'error': 'Customer required to create invoice'}), 400

        # Check for existing open invoice first
        existing = CustomerInvoice.query.filter(
            CustomerInvoice.user_id == current_user.id,
            CustomerInvoice.customer_id == customer_id_for_create,
            CustomerInvoice.status.in_(['open', 'draft'])
        ).order_by(CustomerInvoice.created_at.desc()).first()

        if existing:
            invoice = existing
            invoice_id = existing.id
        else:
            # Create new invoice
            user = current_user
            next_num = user.next_invoice_number or 1
            prefix = user.invoice_prefix or 'INV'
            inv_number = f"{prefix}-{next_num:03d}"
            user.next_invoice_number = next_num + 1
            try:
                terms_days = int(user.default_payment_terms or 30)
            except:
                terms_days = 30
            today = dt_date.today()
            new_inv = CustomerInvoice(
                user_id=current_user.id,
                customer_id=customer_id_for_create,
                job_card_id=job_card_id_for_create,
                invoice_number=inv_number,
                status='open',
                issue_date=today,
                due_date=today + timedelta(days=terms_days),
                payment_terms=str(terms_days),
                subtotal=0, tax_rate=0, tax_amount=0, total=0,
            )
            db.session.add(new_inv)
            db.session.flush()
            invoice = new_inv
            invoice_id = new_inv.id
    else:
        invoice = CustomerInvoice.query.filter_by(
            id=invoice_id, user_id=current_user.id).first_or_404()

    try:
        cutoff_d = date_type.fromisoformat(cutoff_date)
        cutoff_t = dt_type.strptime(cutoff_time, '%H:%M').time()
        cutoff_dt = dt_type.combine(cutoff_d, cutoff_t)
    except:
        cutoff_dt = dt_type.now()

    # Find all pending entries for this invoice's job/customer
    filters = [LabourEntry.user_id == current_user.id, LabourEntry.status == 'logged']

    if invoice.job_card_id:
        filters.append(LabourEntry.job_card_id == invoice.job_card_id)
    elif invoice.customer_id:
        from app.models.job_card import JobCard
        job_ids = [j.id for j in JobCard.query.filter_by(
            user_id=current_user.id, customer_id=invoice.customer_id).all()]
        filters.append(or_(
            LabourEntry.customer_id == invoice.customer_id,
            LabourEntry.job_card_id.in_(job_ids) if job_ids else db.false()
        ))

    all_entries = LabourEntry.query.filter(*filters).order_by(
        LabourEntry.date_worked, LabourEntry.time_worked).all()

    qualifying = []
    pending_future = []

    for e in all_entries:
        entry_time = e.time_worked if e.time_worked else time_type(9, 0)
        entry_dt = dt_type.combine(e.date_worked, entry_time) if e.date_worked else dt_type.min
        entry_data = e.to_dict()
        entry_data['qualifies'] = entry_dt <= cutoff_dt
        if entry_dt <= cutoff_dt:
            qualifying.append(entry_data)
        else:
            pending_future.append(entry_data)

    total_qualifying = sum(e['charge_total'] for e in qualifying)

    return jsonify({
        'qualifying': qualifying,
        'pending_future': pending_future,
        'total_qualifying': round(total_qualifying, 2),
        'cutoff_datetime': cutoff_dt.isoformat(),
    })
# Thu 16 Apr 2026 10:33:00 BST
