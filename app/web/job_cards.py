"""Job Cards routes - full platform mode only"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.job_card import JobCard
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
    return jsonify({'jobs': [{'id': j.id, 'name': j.name, 'status': j.status_label} for j in jobs]})


@bp.route('/api/attach-supplier-invoice', methods=['POST'])
@login_required
@require_full_mode
def api_attach_supplier_invoice():
    """Attach supplier invoice to job card - called from invoice processing"""
    data = request.get_json()
    invoice_id = data.get('invoice_id')
    job_id = data.get('job_id')

    if not invoice_id:
        return jsonify({'error': 'No invoice ID'}), 400

    from app.models.invoice import Invoice
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first_or_404()

    if job_id == 'new':
        # Create new job card on the fly
        customer_id = data.get('customer_id') or invoice.platform_customer_id
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
        invoice.job_card_id = job.id
    elif job_id:
        job = JobCard.query.filter_by(id=job_id, user_id=current_user.id).first_or_404()
        invoice.job_card_id = job.id
    
    db.session.commit()
    return jsonify({'success': True, 'job_id': invoice.job_card_id})
