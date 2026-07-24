"""Job Cards routes.

Jobs are accounting-mode-independent (sync, full AND both) — gated by @require_jobs (the ENABLE_JOBS
flag), NOT by platform_mode. The ONE place that still branches on platform_mode is the supplier-invoice
attach: the FK link (Invoice.job_card_id) is always set, but the full-suite CustomerInvoice draft is
only built for full/both users (sync users push to QuickBooks/Xero and have no CustomerInvoice)."""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.job_card import JobCard, JobSnapshot
from app.models.customer_invoice import CustomerInvoiceLine
from app.models.customer import Customer
from app.utils.access import require_jobs
from app.services.customer_link import user_sync_source, resolve_local_customer
from app.utils.money import money, to_decimal
from app.utils.tax import effective_output_rate, output_rate_unconfigured, OUTPUT_RATE_UNSET_MESSAGE
from datetime import datetime

bp = Blueprint('job_cards', __name__, url_prefix='/jobs')


def _full_suite(user):
    """True when the user runs the GoZappify-native invoicing surface (not pure sync)."""
    return user.platform_mode in ('full', 'both')


def _freeze_snapshot(job):
    """Freeze a versioned completion snapshot for ``job`` (does not commit — caller commits).

    Append-only / versioned: re-completing a re-opened job writes a NEW row (version + 1); prior
    versions are preserved so history is never lost. Figures come from the single source of truth
    (compute_job_financials); metadata is copied in so the snapshot is self-contained. A pay-rise or
    price change after this point can never rewrite the frozen numbers."""
    from app.services.job_financials import compute_job_financials
    last = job.snapshots.order_by(JobSnapshot.snapshot_version.desc()).first()
    version = (last.snapshot_version + 1) if last else 1
    fin = compute_job_financials(job)
    snap = JobSnapshot(
        job_card_id=job.id, user_id=job.user_id, snapshot_version=version,
        frozen_at=datetime.utcnow(), status_at_freeze='complete',
        job_type=job.job_type, room_count=job.room_count, room_types=job.room_types,
        floor_area_sqm=job.floor_area_sqm,
        **fin,
    )
    db.session.add(snap)
    return snap


@bp.route('/')
@login_required
@require_jobs
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

    # Customer dropdown source depends on mode: sync users pick from their accounting software
    # (served client-side from CustomerCache via the shared picker — no local Customer rows exist);
    # full/both users pick from the local Customer table (unchanged). 'both' has local customers, so
    # only PURE sync uses the cache path.
    use_cache = current_user.platform_mode == 'sync'
    sync_source = user_sync_source(current_user) if use_cache else None
    customers = ([] if use_cache
                 else Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all())

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
        use_cache=use_cache,
        sync_source=sync_source,
        status_filter=status_filter,
        counts=counts,
        customer_id=customer_id,
    )


@bp.route('/create', methods=['POST'])
@login_required
@require_jobs
def create():
    """Create a new job card"""
    data = request.get_json() or request.form
    name = data.get('name', '').strip()

    # Sync mode: the picker sends an external (QBO/Xero) customer id — materialise / find the local
    # Customer for the FK. Full/both mode sends a local customer_id directly (unchanged).
    external_customer_id = data.get('external_customer_id')
    if external_customer_id:
        cust = resolve_local_customer(current_user.id, user_sync_source(current_user),
                                      external_customer_id, fallback_name=data.get('customer_name'))
        if not cust:
            msg = 'Could not resolve that customer — refresh the customer list and try again.'
            if request.is_json:
                return jsonify({'error': msg}), 400
            flash(msg, 'error')
            return redirect(url_for('job_cards.index'))
        customer_id = cust.id
    else:
        customer_id = data.get('customer_id')

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
@require_jobs
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
@require_jobs
def update_status(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    new_status = data.get('status')
    if new_status in JobCard.STATUSES:
        job.status = new_status
        if new_status == 'complete':
            if not job.end_date:
                from datetime import date
                job.end_date = date.today()
            # Freeze a versioned snapshot on completion (the pricing-reference record). Re-opening
            # later preserves this; re-completing writes a new version.
            _freeze_snapshot(job)
        db.session.commit()
        return jsonify({'success': True, 'status': job.status_label})
    return jsonify({'error': 'Invalid status'}), 400


@bp.route('/<int:job_id>/attach-invoice', methods=['POST'])
@login_required
@require_jobs
def attach_invoice(job_id):
    """Attach a supplier invoice to this job"""
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    from app.models.invoice import Invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()
    invoice.job_card_id = job_id   # FK-only; attaching an already-synced invoice never re-pushes to QB
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:job_id>/attachable-invoices')
@login_required
@require_jobs
def attachable_invoices(job_id):
    """List the user's processed supplier invoices for the job-side 'attach existing invoice' picker.

    Returns ALL supplier invoices (synced AND unsynced) with their sync status and current job link.
    The UI SHOWS status but never restricts by it — attach is retrospective and sync-independent. An
    invoice already on another job is included (attaching here MOVES it — a plain FK overwrite)."""
    JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()  # tenant guard
    from app.models.invoice import Invoice
    search = (request.args.get('q') or '').strip()
    q = (Invoice.query
         .filter_by(user_id=current_user.id)
         .filter(db.or_(Invoice.document_type.is_(None), Invoice.document_type != 'quote')))
    if search:
        like = f'%{search}%'
        q = q.filter(db.or_(Invoice.invoice_number.ilike(like),
                            Invoice.supplier_name.ilike(like),
                            Invoice.job_reference.ilike(like)))
    invoices = q.order_by(Invoice.created_at.desc()).limit(200).all()
    job_names = {j.id: j.name for j in JobCard.query.filter_by(user_id=current_user.id).all()}
    result = [{
        'id': inv.id,
        'invoice_number': inv.invoice_number,
        'supplier_name': inv.supplier_name,
        'job_reference': inv.job_reference,
        'date': inv.created_at.strftime('%d %b %Y') if inv.created_at else '',
        'total_cost': float(inv.total_cost or 0),
        'synced': bool(inv.qb_synced_at or inv.xero_synced_at),
        'current_job_id': inv.job_card_id,
        'current_job_name': job_names.get(inv.job_card_id) if inv.job_card_id else None,
        'attached_here': inv.job_card_id == job_id,
    } for inv in invoices]
    return jsonify({'invoices': result})


@bp.route('/detach-invoice', methods=['POST'])
@login_required
@require_jobs
def detach_invoice():
    """Detach a supplier invoice from its job (job_card_id -> NULL). FK-only; never touches QB/Xero
    or the invoice's sync state. To MOVE, just attach to another job (overwrites the FK)."""
    from app.models.invoice import Invoice
    data = request.get_json() or {}
    invoice = Invoice.query.filter_by(id=data.get('invoice_id'), user_id=current_user.id).first_or_404()
    invoice.job_card_id = None
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:job_id>/update-notes', methods=['POST'])
@login_required
@require_jobs
def update_notes(job_id):
    job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    job.notes = data.get('notes', '')
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/all-open')
@login_required
@require_jobs
def api_all_open():
    from app.models.customer import Customer
    jobs = JobCard.query.filter_by(user_id=current_user.id).filter(
        JobCard.status.in_(['new', 'in_progress'])
    ).order_by(JobCard.created_at.desc()).all()
    result = []
    for j in jobs:
        result.append({
            'id': j.id,
            'name': j.name,
            'status': j.status_label,
            'customer_name': j.customer.display_name if j.customer else '',
        })
    return jsonify({'jobs': result})


@bp.route('/api/customer/<int:customer_id>/open')
@login_required
@require_jobs
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
@require_jobs
def api_attach_supplier_invoice():
    """Attach supplier invoice to job card and merge into draft customer invoice"""
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    job_id = data.get('job_id')
    invoice_mode = data.get('invoice_mode', 'itemised')  # itemised or summary

    if not invoice_id:
        return jsonify({'error': 'No invoice ID'}), 400

    # Output-rate config is a prerequisite only for the full-suite CustomerInvoice built below;
    # sync users (FK link only) don't need it.
    if _full_suite(current_user) and output_rate_unconfigured(current_user):
        return jsonify({'error': OUTPUT_RATE_UNSET_MESSAGE}), 400

    from app.models.invoice import Invoice, InvoiceItem
    from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
    from app.models.user import User
    from datetime import date, timedelta

    supplier_inv = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()

    # Create job card if needed
    if job_id == 'new':
        # Sync mode: resolve the picked external (QBO/Xero) customer to a local Customer for the FK.
        external_customer_id = data.get('external_customer_id')
        if external_customer_id:
            cust = resolve_local_customer(current_user.id, user_sync_source(current_user),
                                          external_customer_id, fallback_name=data.get('customer_name'))
            customer_id = cust.id if cust else None
        else:
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

    # Attach supplier invoice to job (the FK link — mode-agnostic, retrospective, sync-independent).
    supplier_inv.job_card_id = job.id

    # Sync mode: the link IS the whole operation. Sync users push supplier invoices straight to
    # QuickBooks/Xero and have no native CustomerInvoice — so set the link and stop. This is the ONE
    # behavioural branch; the full-suite path below is unchanged.
    if not _full_suite(current_user):
        db.session.commit()
        return jsonify({'success': True, 'job_id': job.id, 'customer_invoice_id': None,
                        'invoice_action': 'linked', 'message': 'Invoice attached to job'})

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
            tax_rate=effective_output_rate(current_user),  # snapshot: 0 if unregistered
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

    # Load existing lines as list
    existing_line_list = CustomerInvoiceLine.query.filter_by(
        customer_invoice_id=customer_inv.id).all()

    # Build lookup of existing lines by part number
    existing_lines = {
        line.description.split('|')[0].strip(): line
        for line in existing_line_list
        if line.line_type == 'itemised'
    }

    # Also build by part number stored in description prefix
    part_lookup = {}
    for line in existing_line_list:
        if line.line_type == 'itemised' and '|' in line.description:
            pn = line.description.split('|')[0].strip()
            part_lookup[pn] = line

    for item in supplier_items:
        sell_price = to_decimal(item.selling_price or item.calculated_selling_price or 0)
        qty = to_decimal(item.quantity or 1)
        desc = item.description or 'Materials'
        part_num = (item.part_number or '').strip().upper()

        # Try to find existing line by part number
        existing = None
        if part_num:
            # Check part number lookup
            existing = part_lookup.get(part_num)
            if not existing:
                # Search existing lines
                for line in existing_line_list:
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
            # Update quantity and use HIGHER price (Decimal throughout)
            existing.quantity = to_decimal(existing.quantity) + qty
            if sell_price > to_decimal(existing.unit_price):
                existing.unit_price = sell_price
            existing.line_total = money(to_decimal(existing.quantity) * to_decimal(existing.unit_price))
        else:
            # Create new line - store part number in description as prefix
            line_desc = f"{part_num}|{desc}" if part_num else desc
            sort_order = CustomerInvoiceLine.query.filter_by(customer_invoice_id=customer_inv.id).count()
            new_line = CustomerInvoiceLine(
                customer_invoice_id=customer_inv.id,
                description=line_desc,
                quantity=qty,
                unit_price=sell_price,
                line_total=money(qty * sell_price),
                line_type='itemised',
                sort_order=sort_order,
            )
            db.session.add(new_line)
            if part_num:
                part_lookup[part_num] = new_line


def _merge_summary(customer_inv, supplier_items, is_new):
    """Merge supplier invoice items into customer invoice - summary mode"""
    from app.models.customer_invoice import CustomerInvoiceLine

    new_total = money(sum(
        (money(to_decimal(i.selling_price or i.calculated_selling_price or 0) * to_decimal(i.quantity or 1))
         for i in supplier_items),
        to_decimal(0)))

    # Find existing Materials line
    materials_line = None
    for line in CustomerInvoiceLine.query.filter_by(customer_invoice_id=customer_inv.id).all():
        if line.line_type == 'summary' or 'materials' in line.description.lower():
            materials_line = line
            break

    if materials_line:
        # Add to existing total (Decimal)
        materials_line.line_total = money(to_decimal(materials_line.line_total or 0) + new_total)
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
    # Line-authority, Decimal end-to-end (ROUND_HALF_UP) — was float with tax never rounded.
    subtotal = money(sum((money(l.line_total or 0) for l in lines), to_decimal(0)))
    tax = money(subtotal * to_decimal(customer_inv.tax_rate or 0) / 100)
    customer_inv.subtotal = subtotal
    customer_inv.tax_amount = tax
    customer_inv.total = money(subtotal + tax)
    customer_inv.updated_at = datetime.utcnow()


@bp.route('/<int:job_id>/delete', methods=['POST'])
@login_required
@require_jobs
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
