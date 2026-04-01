"""Job Cards routes - full platform mode only"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.job_card import JobCard
from app.models.customer_invoice import CustomerInvoiceLine
from app.models.customer import Customer
from datetime import datetime

bp = Blueprint('job_cards', __name__, url_prefix='/jobs')


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
    status_filter = request.args.get('status', 'active')
    customer_id = request.args.get('customer_id', type=int)

    query = JobCard.query.filter_by(user_id=current_user.id)

    if status_filter == 'active':
        query = query.filter(JobCard.status.in_(['new', 'in_progress']))
    elif status_filter != 'all':
        query = query.filter_by(status=status_filter)

    if customer_id:
        query = query.filter_by(customer_id=customer_id)

    jobs = query.order_by(JobCard.created_at.desc()).all()
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()

    counts = {
        'active': JobCard.query.filter_by(user_id=current_user.id).filter(
            JobCard.status.in_(['new', 'in_progress'])).count(),
        'complete': JobCard.query.filter_by(user_id=current_user.id, status='complete').count(),
        'paid': JobCard.query.filter_by(user_id=current_user.id, status='paid').count(),
        'all': JobCard.query.filter_by(user_id=current_user.id).count(),
    }

    return render_template('job_cards/index.html',
        jobs=jobs,
        customers=customers,
        status_filter=status_filter,
        counts=counts,
        customer_id=customer_id,
    )


@bp.route('/create', methods=['POST'])
@login_required
@require_full_mode
def create():
    """Create a new job card"""
    data = request.get_json() or request.form
    customer_id = data.get('customer_id')
    name = data.get('name', '').strip()

    if not customer_id or not name:
        if request.is_json:
            return jsonify({'error': 'Customer and job name required'}), 400
        flash('Customer and job name required', 'error')
        return redirect(url_for('job_cards.index'))

    job = JobCard(
        user_id=current_user.id,
        customer_id=int(customer_id),
        name=name,
        description=data.get('description', ''),
        status='new',
        notes=data.get('notes', ''),
    )

    if data.get('start_date'):
        try:
            job.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        except ValueError:
            pass

    if data.get('quote_id'):
        job.quote_id = int(data['quote_id'])

    db.session.add(job)
    db.session.commit()

    if request.is_json:
        return jsonify({'success': True, 'job_id': job.id, 'job_name': job.name})

    flash(f'Job "{name}" created successfully', 'success')
    return redirect(url_for('job_cards.view', job_id=job.id))


@bp.route('/<int:job_id>')
@login_required
@require_full_mode
def view(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    from app.models.customer_quote import CustomerQuote
    available_quotes = CustomerQuote.query.filter_by(
        user_id=current_user.id,
        customer_id=job.customer_id,
        status='accepted'
    ).all()
    return render_template('job_cards/view.html',
        job=job,
        available_quotes=available_quotes,
    )


@bp.route('/<int:job_id>/update-status', methods=['POST'])
@login_required
@require_full_mode
def update_status(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    new_status = data.get('status')
    if new_status in JobCard.STATUSES:
        job.status = new_status
        if new_status == 'complete' and not job.end_date:
            from datetime import date
            job.end_date = date.today()
        db.session.commit()
        return jsonify({'success': True, 'status': job.status_label})
    return jsonify({'error': 'Invalid status'}), 400


@bp.route('/<int:job_id>/attach-invoice', methods=['POST'])
@login_required
@require_full_mode
def attach_invoice(job_id):
    """Attach a supplier invoice to this job"""
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    from app.models.invoice import Invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    invoice.job_card_id = job_id
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:job_id>/update-notes', methods=['POST'])
@login_required
@require_full_mode
def update_notes(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    job.notes = data.get('notes', '')
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/customer/<int:customer_id>/open')
@login_required
@require_full_mode
def api_customer_jobs(customer_id):
    """Get open job cards for a customer - used in invoice processing flow"""
    jobs = JobCard.query.filter_by(
        user_id=current_user.id,
        customer_id=customer_id
    ).filter(JobCard.status.in_(['new', 'in_progress'])).order_by(
        JobCard.created_at.desc()).all()
    from app.models.customer_invoice import CustomerInvoice
    result = []
    for j in jobs:
        # Check for existing draft/open invoice on this job
        draft_inv = CustomerInvoice.query.filter_by(
            user_id=current_user.id,
            job_card_id=j.id,
        ).filter(CustomerInvoice.status.in_(['open', 'draft'])).first()
        result.append({
            'id': j.id,
            'name': j.name,
            'status': j.status_label,
            'draft_invoice_id': draft_inv.id if draft_inv else None,
            'draft_invoice_number': draft_inv.invoice_number if draft_inv else None,
            'draft_invoice_mode': draft_inv.invoice_mode if draft_inv else None,
            'draft_invoice_status': draft_inv.status if draft_inv else None,
        })
    return jsonify({'jobs': result})


@bp.route('/api/attach-supplier-invoice', methods=['POST'])
@login_required
@require_full_mode
def api_attach_supplier_invoice():
    """Attach supplier invoice to job card and merge into draft customer invoice"""
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    job_id = data.get('job_id')
    invoice_mode = data.get('invoice_mode', 'itemised')  # itemised or summary

    if not invoice_id:
        return jsonify({'error': 'No invoice ID'}), 400

    from app.models.invoice import Invoice, InvoiceItem
    from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
    from app.models.user import User
    from datetime import date, timedelta

    supplier_inv = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()

    # Create job card if needed
    if job_id == 'new':
        customer_id = data.get('customer_id') or supplier_inv.platform_customer_id
        job_name = data.get('job_name', 'New Job')
        if not customer_id:
            return jsonify({'error': 'Customer required to create job'}), 400
        job = JobCard(
            user_id=current_user.id,
            customer_id=int(customer_id),
            name=job_name,
            status='in_progress',
        )
        db.session.add(job)
        db.session.flush()
    elif job_id:
        job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    else:
        return jsonify({'error': 'No job specified'}), 400

    # Attach supplier invoice to job
    supplier_inv.job_card_id = job.id

    # Get items from supplier invoice
    items = InvoiceItem.query.filter_by(invoice_id=supplier_inv.id).all()
    if not items:
        db.session.commit()
        return jsonify({'success': True, 'job_id': job.id, 'message': 'Attached but no items found'})

    # Find existing DRAFT customer invoice for this job
    existing_inv = CustomerInvoice.query.filter_by(
        user_id=current_user.id,
        job_card_id=job.id,
    ).filter(CustomerInvoice.status.in_(['open', 'draft'])).first()

    user = current_user
    today = date.today()
    try:
        terms_days = int(user.default_payment_terms or 30)
    except:
        terms_days = 30
    due = today + timedelta(days=terms_days)

    if not existing_inv:
        # Generate invoice number
        next_num = user.next_invoice_number or 1
        prefix = user.invoice_prefix or 'INV'
        inv_number = f"{prefix}-{next_num:03d}"
        user.next_invoice_number = next_num + 1

        existing_inv = CustomerInvoice(
            user_id=current_user.id,
            customer_id=job.customer_id,
            invoice_number=inv_number,
            status='open',
            invoice_mode=invoice_mode,
            job_card_id=job.id,
            issue_date=today,
            due_date=due,
            payment_terms=str(terms_days),
            subtotal=0,
            tax_rate=0,
            tax_amount=0,
            total=0,
            notes='',
        )
        db.session.add(existing_inv)
        db.session.flush()
        is_new = True
    else:
        is_new = False

    if invoice_mode == 'summary':
        _merge_summary(existing_inv, items, is_new)
    else:
        _merge_itemised(existing_inv, items, is_new)

    # Recalculate invoice totals
    _recalculate_invoice(existing_inv)
    db.session.commit()

    return jsonify({
        'success': True,
        'job_id': job.id,
        'customer_invoice_id': existing_inv.id,
        'customer_invoice_number': existing_inv.invoice_number,
        'is_new': is_new,
        'message': f'{"Created" if is_new else "Updated"} draft invoice {existing_inv.invoice_number}'
    })


def _merge_itemised(customer_inv, supplier_items, is_new):
    """Merge supplier invoice items into customer invoice - itemised mode"""
    from app.models.customer_invoice import CustomerInvoiceLine

    # Build lookup of existing lines by part number
    existing_lines = {
        line.description.split('|')[0].strip(): line
        for line in customer_inv.lines
        if line.line_type == 'itemised'
    }

    # Also build by part number stored in description prefix
    part_lookup = {}
    for line in customer_inv.lines:
        if line.line_type == 'itemised' and '|' in line.description:
            pn = line.description.split('|')[0].strip()
            part_lookup[pn] = line

    for item in supplier_items:
        sell_price = float(item.selling_price or item.calculated_selling_price or 0)
        qty = float(item.quantity or 1)
        desc = item.description or 'Materials'
        part_num = (item.part_number or '').strip().upper()

        # Try to find existing line by part number
        existing = None
        if part_num:
            # Check part number lookup
            existing = part_lookup.get(part_num)
            if not existing:
                # Search existing lines
                for line in customer_inv.lines:
                    if line.line_type == 'itemised':
                        stored_pn = ''
                        if hasattr(line, 'part_number_ref'):
                            stored_pn = line.part_number_ref or ''
                        # Check description prefix
                        if '|' in line.description:
                            stored_pn = line.description.split('|')[0].strip()
                        if stored_pn.upper() == part_num:
                            existing = line
                            break

        if existing:
            # Update quantity and use HIGHER price
            existing.quantity = existing.quantity + qty
            if sell_price > existing.unit_price:
                existing.unit_price = sell_price
            existing.line_total = existing.quantity * existing.unit_price
        else:
            # Create new line - store part number in description as prefix
            line_desc = f"{part_num}|{desc}" if part_num else desc
            sort_order = len(customer_inv.lines)
            new_line = CustomerInvoiceLine(
                customer_invoice_id=customer_inv.id,
                description=line_desc,
                quantity=qty,
                unit_price=sell_price,
                line_total=qty * sell_price,
                line_type='itemised',
                sort_order=sort_order,
            )
            db.session.add(new_line)
            if part_num:
                part_lookup[part_num] = new_line


def _merge_summary(customer_inv, supplier_items, is_new):
    """Merge supplier invoice items into customer invoice - summary mode"""
    from app.models.customer_invoice import CustomerInvoiceLine

    new_total = sum(float(i.selling_price or i.calculated_selling_price or 0) * float(i.quantity or 1) for i in supplier_items)

    # Find existing Materials line
    materials_line = None
    for line in customer_inv.lines:
        if line.line_type == 'summary' or 'materials' in line.description.lower():
            materials_line = line
            break

    if materials_line:
        # Add to existing total
        materials_line.line_total = float(materials_line.line_total or 0) + new_total
        materials_line.unit_price = materials_line.line_total
        materials_line.quantity = 1
    else:
        new_line = CustomerInvoiceLine(
            customer_invoice_id=customer_inv.id,
            description='Materials',
            quantity=1,
            unit_price=new_total,
            line_total=new_total,
            line_type='summary',
            sort_order=0,
        )
        db.session.add(new_line)


def _recalculate_invoice(customer_inv):
    """Recalculate invoice subtotal, tax and total from lines"""
    db.session.flush()
    lines = CustomerInvoiceLine.query.filter_by(customer_invoice_id=customer_inv.id).all()
    subtotal = sum(float(l.line_total or 0) for l in lines)
    tax = subtotal * (float(customer_inv.tax_rate or 0) / 100)
    customer_inv.subtotal = subtotal
    customer_inv.tax_amount = tax
    customer_inv.total = subtotal + tax
    customer_inv.updated_at = datetime.utcnow()


@bp.route('/<int:job_id>/delete', methods=['POST'])
@login_required
@require_full_mode
def delete(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    # Detach any linked invoices first
    from app.models.invoice import Invoice
    from app.models.customer_invoice import CustomerInvoice
    Invoice.query.filter_by(job_card_id=job_id).update({'job_card_id': None})
    CustomerInvoice.query.filter_by(job_card_id=job_id).update({'job_card_id': None})
    db.session.delete(job)
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True})
    flash(f'Job "{job.name}" deleted', 'success')
    return redirect(url_for('job_cards.index'))
