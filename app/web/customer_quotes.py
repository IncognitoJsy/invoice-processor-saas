"""Customer Quotes routes for full platform mode"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app.extensions import db
from app.models.customer_quote import CustomerQuote, CustomerQuoteLine
from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
from app.models.customer import Customer
from datetime import datetime, date, timedelta

bp = Blueprint('customer_quotes', __name__, url_prefix='/customer-quotes')


def _next_quote_number(user):
    num = user.next_quote_number or 1
    user.next_quote_number = num + 1
    return f"{user.quote_prefix or 'QUO'}-{num:03d}"


@bp.route('/')
@login_required
def index():
    quotes = CustomerQuote.query.filter_by(user_id=current_user.id)\
        .order_by(CustomerQuote.created_at.desc()).all()
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    return render_template('customer_quotes/index.html', quotes=quotes, customers=customers)


@bp.route('/new')
@login_required
def new():
    """Manual quote creation page"""
    from app.models.customer import Customer
    from app.models.product_service import ProductService
    customer_id = request.args.get('customer_id', type=int)
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    selected_customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first() if customer_id else None
    products = ProductService.query.filter_by(user_id=current_user.id).order_by(ProductService.name).all()
    from datetime import date, timedelta
    today = date.today()
    default_terms = current_user.default_payment_terms or '30'
    due_date = today + timedelta(days=30)
    return render_template('customer_quotes/new.html',
        customers=customers,
        selected_customer=selected_customer,
        products=products,
        today=today.strftime('%Y-%m-%d'),
        default_expiry=due_date.strftime('%Y-%m-%d'),
        default_due=due_date.strftime('%Y-%m-%d'),
        default_terms=default_terms,
        next_number=f"{current_user.quote_prefix or 'QUO'}-{current_user.next_quote_number or 1:03d}",
        doc_type='quote',
        back_url=url_for('customer_quotes.index'),
    )


@bp.route('/create', methods=['POST'])
@login_required
def create():
    customer_id = request.form.get('customer_id') or None
    quote = CustomerQuote(
        user_id=current_user.id,
        customer_id=int(customer_id) if customer_id else None,
        quote_number=_next_quote_number(current_user),
        status='draft',
        issue_date=date.today(),
        expiry_date=date.today() + timedelta(days=30),
        tax_rate=current_user.tax_rate or 0.0,
        payment_terms=current_user.default_payment_terms or '30',
        notes=current_user.invoice_notes or '',
    )
    quote.generate_token()
    db.session.add(quote)
    db.session.commit()
    return redirect(url_for('customer_quotes.view', quote_id=quote.id))


@bp.route('/<int:quote_id>')
@login_required
def view(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    customers = Customer.query.filter_by(user_id=current_user.id).order_by(Customer.name).all()
    return render_template('customer_quotes/view.html', quote=quote, customers=customers)


@bp.route('/<int:quote_id>/add-line', methods=['POST'])
@login_required
def add_line(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    if quote.status in ('accepted', 'converted'):
        return jsonify({'error': 'Cannot edit accepted quote'}), 400
    data = request.get_json()
    max_order = db.session.query(db.func.max(CustomerQuoteLine.sort_order))\
        .filter_by(quote_id=quote_id).scalar() or 0
    line = CustomerQuoteLine(
        quote_id=quote_id,
        description=data.get('description', ''),
        quantity=float(data.get('quantity', 1)),
        unit_price=float(data.get('unit_price', 0)),
        sort_order=max_order + 1
    )
    line.calculate_total()
    db.session.add(line)
    quote.recalculate_totals()
    db.session.commit()
    return jsonify({'success': True, 'line_id': line.id, 'line_total': line.line_total,
                    'subtotal': quote.subtotal, 'tax_amount': quote.tax_amount, 'total': quote.total})


@bp.route('/<int:quote_id>/delete-line/<int:line_id>', methods=['POST'])
@login_required
def delete_line(quote_id, line_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    line = CustomerQuoteLine.query.filter_by(id=line_id, quote_id=quote_id).first_or_404()
    db.session.delete(line)
    quote.recalculate_totals()
    db.session.commit()
    return jsonify({'success': True, 'subtotal': quote.subtotal,
                    'tax_amount': quote.tax_amount, 'total': quote.total})


@bp.route('/<int:quote_id>/update-line/<int:line_id>', methods=['POST'])
@login_required
def update_line(quote_id, line_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    line = CustomerQuoteLine.query.filter_by(id=line_id, quote_id=quote_id).first_or_404()
    data = request.get_json()
    if 'description' in data:
        line.description = data['description']
    if 'quantity' in data:
        line.quantity = float(data['quantity'])
    if 'unit_price' in data:
        line.unit_price = float(data['unit_price'])
    line.calculate_total()
    quote.recalculate_totals()
    db.session.commit()
    return jsonify({'success': True, 'line_total': line.line_total,
                    'subtotal': quote.subtotal, 'tax_amount': quote.tax_amount, 'total': quote.total})


@bp.route('/<int:quote_id>/update', methods=['POST'])
@login_required
def update(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    if 'customer_id' in data:
        quote.customer_id = int(data['customer_id']) if data['customer_id'] else None
    if 'expiry_date' in data:
        try:
            quote.expiry_date = datetime.strptime(data['expiry_date'], '%Y-%m-%d').date()
        except:
            pass
    if 'notes' in data:
        quote.notes = data['notes']
    if 'internal_notes' in data:
        quote.internal_notes = data['internal_notes']
    if 'payment_terms' in data:
        quote.payment_terms = data['payment_terms']
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:quote_id>/send', methods=['POST'])
@login_required
def send_quote(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    if not quote.customer or not quote.customer.email:
        return jsonify({'error': 'Customer has no email address'}), 400
    if not quote.lines.count():
        return jsonify({'error': 'Quote has no line items'}), 400

    try:
        from app.services.pdf_generator import generate_quote_pdf
        from app.services.email_sender import send_quote_email
        pdf = generate_quote_pdf(quote, current_user)
        base_url = __import__('os').getenv('APP_URL', 'https://gozappify.com')
        accept_url = f"{base_url}/customer-quotes/accept/{quote.acceptance_token}"
        send_quote_email(current_user, quote, pdf, accept_url)
        quote.status = 'sent'
        quote.sent_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'message': f'Quote sent to {quote.customer.email}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/<int:quote_id>/pdf')
@login_required
def download_pdf(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    from app.services.pdf_generator import generate_quote_pdf
    pdf = generate_quote_pdf(quote, current_user)
    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{quote.quote_number}.pdf"'})


@bp.route('/<int:quote_id>/preview')
@login_required
def preview(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    return render_template('customer_quotes/preview.html', quote=quote)


@bp.route('/accept/<token>')
def accept_page(token):
    """Public page — customer clicks to accept quote"""
    quote = CustomerQuote.query.filter_by(acceptance_token=token).first_or_404()
    if quote.status in ('converted',):
        return render_template('customer_quotes/already_converted.html', quote=quote)
    if quote.status == 'accepted':
        return render_template('customer_quotes/already_accepted.html', quote=quote)
    return render_template('customer_quotes/accept.html', quote=quote, token=token)


@bp.route('/accept/<token>/confirm', methods=['POST'])
def accept_confirm(token):
    """Customer confirms acceptance"""
    quote = CustomerQuote.query.filter_by(acceptance_token=token).first_or_404()
    if quote.status in ('accepted', 'converted'):
        return render_template('customer_quotes/already_accepted.html', quote=quote)

    quote.status = 'accepted'
    quote.accepted_at = datetime.utcnow()
    quote.accepted_by_name = request.form.get('name', '')
    db.session.commit()

    # Notify the contractor
    try:
        from app.models.user import User
        user = db.session.get(User, quote.user_id)
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        base_url = __import__('os').getenv('APP_URL', 'https://gozappify.com')
        quote_url = f"{base_url}/customer-quotes/{quote.id}"
        email_service.send_quote_accepted_notification(user, quote, quote_url)
    except Exception as e:
        pass

    return render_template('customer_quotes/accepted_thanks.html', quote=quote)


@bp.route('/<int:quote_id>/convert', methods=['POST'])
@login_required
def convert_to_invoice(quote_id):
    """Convert accepted quote to customer invoice"""
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    if quote.status not in ('accepted', 'sent', 'draft'):
        return jsonify({'error': 'Quote cannot be converted'}), 400

    from datetime import timedelta
    # Create invoice
    inv_num = current_user.next_invoice_number or 1
    current_user.next_invoice_number = inv_num + 1
    invoice_number = f"{current_user.invoice_prefix or 'INV'}-{inv_num:03d}"

    terms = quote.payment_terms or current_user.default_payment_terms or '30'
    due = date.today() + timedelta(days=int(terms))

    invoice = CustomerInvoice(
        user_id=current_user.id,
        customer_id=quote.customer_id,
        invoice_number=invoice_number,
        status='open',
        issue_date=date.today(),
        due_date=due,
        subtotal=quote.subtotal,
        tax_rate=quote.tax_rate,
        tax_amount=quote.tax_amount,
        total=quote.total,
        notes=quote.notes,
        payment_terms=terms,
        mode='itemised',
    )
    db.session.add(invoice)
    db.session.flush()

    # Copy lines
    for i, line in enumerate(quote.lines.order_by(CustomerQuoteLine.sort_order)):
        inv_line = CustomerInvoiceLine(
            customer_invoice_id=invoice.id,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            line_total=line.line_total,
            sort_order=i,
        )
        db.session.add(inv_line)

    quote.status = 'converted'
    quote.converted_invoice_id = invoice.id
    db.session.commit()

    return jsonify({'success': True, 'invoice_id': invoice.id,
                    'invoice_number': invoice_number,
                    'redirect': url_for('customer_invoices.view', invoice_id=invoice.id)})


@bp.route('/<int:quote_id>/accept-manual', methods=['POST'])
@login_required
def accept_manual(quote_id):
    """Manually mark quote as accepted from customer profile"""
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    name = data.get('name', '')
    date_str = data.get('date', '')
    convert = data.get('convert', False)

    quote.status = 'accepted'
    quote.accepted_at = datetime.strptime(date_str, '%Y-%m-%d') if date_str else datetime.utcnow()
    quote.accepted_by_name = name
    db.session.commit()

    if convert:
        # Convert to invoice
        from datetime import timedelta
        inv_num = current_user.next_invoice_number or 1
        current_user.next_invoice_number = inv_num + 1
        invoice_number = f"{current_user.invoice_prefix or 'INV'}-{inv_num:03d}"
        from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
        from datetime import date
        terms = quote.payment_terms or current_user.default_payment_terms or '30'
        due = date.today() + timedelta(days=int(terms) if terms.isdigit() else 30)
        invoice = CustomerInvoice(
            user_id=current_user.id,
            customer_id=quote.customer_id,
            invoice_number=invoice_number,
            status='open',
            issue_date=date.today(),
            due_date=due,
            subtotal=quote.subtotal,
            tax_rate=quote.tax_rate,
            tax_amount=quote.tax_amount,
            total=quote.total,
            notes=quote.notes,
            payment_terms=terms,
        )
        db.session.add(invoice)
        db.session.flush()
        for i, line in enumerate(quote.lines.order_by(CustomerQuoteLine.sort_order)):
            inv_line = CustomerInvoiceLine(
                customer_invoice_id=invoice.id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_total=line.line_total,
                sort_order=i,
            )
            db.session.add(inv_line)
        quote.status = 'converted'
        quote.converted_invoice_id = invoice.id
        db.session.commit()
        return jsonify({'success': True, 'redirect': url_for('customer_invoices.view', invoice_id=invoice.id)})

    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:quote_id>/decline', methods=['POST'])
@login_required
def decline(quote_id):
    """Mark quote as declined"""
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    quote.status = 'declined'
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/<int:quote_id>/delete', methods=['POST'])
@login_required
def delete(quote_id):
    quote = CustomerQuote.query.filter_by(id=quote_id, user_id=current_user.id).first_or_404()
    if quote.status == 'converted':
        return jsonify({'error': 'Cannot delete a converted quote'}), 400
    db.session.delete(quote)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/create-manual', methods=['POST'])
@login_required
def create_manual():
    """Create quote from manual entry"""
    from datetime import date, timedelta, datetime as dt
    data = request.get_json()
    quote_num = current_user.next_quote_number or 1
    current_user.next_quote_number = quote_num + 1
    quote_number = f"{current_user.quote_prefix or 'QUO'}-{quote_num:03d}"
    try:
        issue = dt.strptime(data['issue_date'], '%Y-%m-%d').date()
        expiry = dt.strptime(data['due_date'], '%Y-%m-%d').date()
    except:
        issue = date.today()
        expiry = date.today() + timedelta(days=30)
    quote = CustomerQuote(
        user_id=current_user.id,
        customer_id=data['customer_id'],
        quote_number=quote_number,
        status='draft',
        issue_date=issue,
        expiry_date=expiry,
        subtotal=data.get('subtotal', 0),
        tax_rate=data.get('tax_rate', 0),
        tax_amount=data.get('tax_amount', 0),
        total=data.get('total', 0),
        notes=data.get('notes', ''),
        payment_terms=data.get('payment_terms', '30'),
    )
    quote.generate_token()
    db.session.add(quote)
    db.session.flush()
    for line in data.get('lines', []):
        q_line = CustomerQuoteLine(
            quote_id=quote.id,
            description=line['description'],
            quantity=line['quantity'],
            unit_price=line['unit_price'],
            line_total=line['line_total'],
            sort_order=line.get('sort_order', 0),
        )
        db.session.add(q_line)
    db.session.commit()
    return jsonify({'success': True, 'redirect': url_for('customer_quotes.view', quote_id=quote.id)})
