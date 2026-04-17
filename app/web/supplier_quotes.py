"""Supplier Quote Comparison - full platform only"""
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from app.extensions import db
from app.models.supplier_quote import SupplierQuoteSession, SupplierQuote, SupplierQuoteItem
import json

bp = Blueprint('supplier_quotes', __name__, url_prefix='/supplier-quotes')


def require_full_mode(f):
    from functools import wraps
    from flask import abort
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.platform_mode not in ('full', 'both'):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@bp.route('/session/create', methods=['POST'])
@login_required
@require_full_mode
def create_session():
    data = request.get_json()
    session = SupplierQuoteSession(
        user_id=current_user.id,
        job_card_id=data.get('job_card_id'),
        name=data.get('name', 'Quote Comparison'),
        status='comparing',
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({'success': True, 'session_id': session.id})


@bp.route('/session/<int:session_id>', methods=['GET'])
@login_required
@require_full_mode
def get_session(session_id):
    session = SupplierQuoteSession.query.filter_by(
        id=session_id, user_id=current_user.id).first_or_404()
    quotes = [{'id': q.id, 'supplier_name': q.supplier_name,
               'status': q.status, 'item_count': len(q.parsed_items or [])}
              for q in session.quotes]
    items = [i.to_dict() for i in session.items.order_by(
        SupplierQuoteItem.generic_description).all()]
    return jsonify({'session': {
        'id': session.id, 'name': session.name, 'status': session.status,
        'quotes': quotes, 'items': items,
    }})


@bp.route('/session/<int:session_id>/upload', methods=['POST'])
@login_required
@require_full_mode
def upload_quote(session_id):
    """Upload a supplier quote PDF/image for parsing"""
    session = SupplierQuoteSession.query.filter_by(
        id=session_id, user_id=current_user.id).first_or_404()

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    supplier_name = request.form.get('supplier_name', '').strip()
    if not supplier_name:
        return jsonify({'error': 'Supplier name required'}), 400

    # Read file content
    import base64
    file_bytes = file.read()
    file_b64 = base64.standard_b64encode(file_bytes).decode('utf-8')
    filename = file.filename or 'quote.pdf'
    is_pdf = filename.lower().endswith('.pdf')
    media_type = 'application/pdf' if is_pdf else 'image/jpeg'

    # Create quote record
    quote = SupplierQuote(
        session_id=session_id,
        user_id=current_user.id,
        supplier_name=supplier_name,
        original_filename=filename,
        status='processing',
    )
    db.session.add(quote)
    db.session.commit()

    # Parse with Claude
    try:
        parsed = _parse_supplier_quote(file_b64, media_type, supplier_name)
        quote.parsed_items = parsed
        quote.status = 'parsed'
        db.session.commit()
        return jsonify({'success': True, 'quote_id': quote.id,
                       'items_found': len(parsed), 'supplier': supplier_name})
    except Exception as e:
        quote.status = 'error'
        db.session.commit()
        return jsonify({'error': str(e)}), 500


@bp.route('/session/<int:session_id>/compare', methods=['POST'])
@login_required
@require_full_mode
def run_comparison(session_id):
    """AI matches items across all uploaded quotes and finds best prices"""
    session = SupplierQuoteSession.query.filter_by(
        id=session_id, user_id=current_user.id).first_or_404()

    quotes = session.quotes.filter_by(status='parsed').all()
    if len(quotes) < 1:
        return jsonify({'error': 'Upload at least one supplier quote first'}), 400

    markup = float(current_user.default_markup or 30)

    # Gather all parsed items
    all_items = []
    for q in quotes:
        for item in (q.parsed_items or []):
            all_items.append({
                'supplier': q.supplier_name,
                'description': item.get('description', ''),
                'part_number': item.get('part_number', ''),
                'quantity': item.get('quantity', 1),
                'unit_price': item.get('unit_price', 0),
                'unit': item.get('unit', 'each'),
            })

    # Use Claude to match items across suppliers
    matched = _match_items_across_suppliers(all_items, quotes, markup)

    # Clear existing items and save new ones
    SupplierQuoteItem.query.filter_by(session_id=session_id).delete()

    for m in matched:
        item = SupplierQuoteItem(
            session_id=session_id,
            generic_description=m['generic_description'],
            quantity=m.get('quantity', 1),
            unit=m.get('unit', 'each'),
            supplier_data=m['supplier_data'],
            best_price_supplier=m['best_price_supplier'],
            best_price=m['best_price'],
            highest_price=m['highest_price'],
            markup_base=m['highest_price'],
            customer_price=round(m['highest_price'] * (1 + markup / 100), 2),
            selected_supplier=m['best_price_supplier'],
        )
        db.session.add(item)

    session.status = 'compared'
    db.session.commit()

    return jsonify({
        'success': True,
        'items': [i.to_dict() for i in session.items.all()],
        'summary': _build_summary(session),
    })


@bp.route('/session/<int:session_id>/item/<int:item_id>/select-supplier', methods=['POST'])
@login_required
@require_full_mode
def select_supplier(session_id, item_id):
    """Override which supplier to buy an item from"""
    item = SupplierQuoteItem.query.filter_by(
        id=item_id, session_id=session_id).first_or_404()
    data = request.get_json()
    supplier = data.get('supplier')
    if supplier and item.supplier_data and supplier in item.supplier_data:
        item.selected_supplier = supplier
        db.session.commit()
    return jsonify({'success': True})


@bp.route('/session/<int:session_id>/create-quote', methods=['POST'])
@login_required
@require_full_mode
def create_customer_quote(session_id):
    """Generate a GoZappify customer quote from the comparison"""
    from app.models.customer_quote import CustomerQuote, CustomerQuoteLine
    from app.models.job_card import JobCard
    from datetime import date, timedelta

    session = SupplierQuoteSession.query.filter_by(
        id=session_id, user_id=current_user.id).first_or_404()
    data = request.get_json()
    customer_id = data.get('customer_id')

    if not customer_id:
        # Try to get from job card
        if session.job_card_id:
            job = JobCard.query.get(session.job_card_id)
            if job:
                customer_id = job.customer_id
    if not customer_id:
        return jsonify({'error': 'Customer required'}), 400

    items = session.items.all()
    if not items:
        return jsonify({'error': 'Run comparison first'}), 400

    # Build quote
    user = current_user
    next_num = user.next_quote_number or 1
    prefix = user.quote_prefix or 'QUO'
    quote_number = f"{prefix}-{next_num:03d}"
    user.next_quote_number = next_num + 1

    today = date.today()
    try:
        terms_days = int(user.default_payment_terms or 30)
    except:
        terms_days = 30

    subtotal = sum(float(i.customer_price or 0) * float(i.quantity or 1) for i in items)

    quote = CustomerQuote(
        user_id=current_user.id,
        customer_id=customer_id,
        job_card_id=session.job_card_id,
        quote_number=quote_number,
        status='draft',
        issue_date=today,
        expiry_date=today + timedelta(days=30),
        subtotal=subtotal,
        tax_rate=0,
        tax_amount=0,
        total=subtotal,
        notes=data.get('notes', ''),
    )
    db.session.add(quote)
    db.session.flush()

    for i, item in enumerate(items):
        line = CustomerQuoteLine(
            customer_quote_id=quote.id,
            description=item.generic_description,
            quantity=float(item.quantity or 1),
            unit_price=float(item.customer_price or 0),
            line_total=float(item.customer_price or 0) * float(item.quantity or 1),
            sort_order=i,
        )
        db.session.add(line)

    session.status = 'quoted'
    db.session.commit()

    return jsonify({'success': True, 'quote_id': quote.id,
                   'quote_number': quote_number,
                   'redirect': f'/customer-quotes/{quote.id}'})


@bp.route('/session/<int:session_id>/pick-lists', methods=['GET'])
@login_required
@require_full_mode
def pick_lists(session_id):
    """Generate material pick lists per supplier - no prices"""
    session = SupplierQuoteSession.query.filter_by(
        id=session_id, user_id=current_user.id).first_or_404()
    items = session.items.all()

    # Group by selected supplier
    lists = {}
    for item in items:
        supplier = item.selected_supplier or item.best_price_supplier or 'Unknown'
        if supplier not in lists:
            lists[supplier] = []
        supplier_data = item.supplier_data or {}
        s_data = supplier_data.get(supplier, {})
        lists[supplier].append({
            'description': item.generic_description,
            'part_number': s_data.get('part_number', '—'),
            'supplier_description': s_data.get('description', item.generic_description),
            'quantity': float(item.quantity or 1),
            'unit': item.unit or 'each',
        })

    return jsonify({'pick_lists': lists, 'session_name': session.name})


def _parse_supplier_quote(file_b64, media_type, supplier_name):
    """Use Claude to extract line items from a supplier quote"""
    import anthropic
    client = anthropic.Anthropic()

    prompt = f"""You are parsing a supplier quote from {supplier_name}.
Extract ALL line items and return ONLY a JSON array. No other text.

Each item must have:
- description: item description
- part_number: supplier part number (or "" if not found)
- quantity: numeric quantity
- unit: unit of measure (each, metre, box, etc)
- unit_price: unit price as a number (no currency symbols)

Example: [{{"description": "13A Double Socket White", "part_number": "MK123", "quantity": 10, "unit": "each", "unit_price": 3.20}}]

Parse the document and return the JSON array only:"""

    if media_type == 'application/pdf':
        msg = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=4000,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'document',
                     'source': {'type': 'base64', 'media_type': media_type, 'data': file_b64}},
                    {'type': 'text', 'text': prompt}
                ]
            }]
        )
    else:
        msg = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=4000,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image',
                     'source': {'type': 'base64', 'media_type': media_type, 'data': file_b64}},
                    {'type': 'text', 'text': prompt}
                ]
            }]
        )

    text = msg.content[0].text.strip()
    # Strip markdown code blocks if present
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)


def _match_items_across_suppliers(all_items, quotes, markup):
    """Use Claude to match items across suppliers and find best prices"""
    import anthropic
    client = anthropic.Anthropic()

    # Build a structured view of all items per supplier
    supplier_lists = {}
    for q in quotes:
        supplier_lists[q.supplier_name] = q.parsed_items or []

    prompt = f"""You are comparing quotes from multiple suppliers for the same job.

Here are the items from each supplier:
{json.dumps(supplier_lists, indent=2)}

Your job:
1. Match items that are the SAME product across suppliers (even if names/part numbers differ)
2. For each matched group, identify the generic description
3. Find which supplier has the CHEAPEST price and which has the HIGHEST price

Return ONLY a JSON array. No other text. Each element:
{{
  "generic_description": "clear generic name e.g. 13A Double Socket White",
  "quantity": 1,
  "unit": "each",
  "supplier_data": {{
    "SUPPLIER_NAME": {{
      "description": "their exact description",
      "part_number": "their part number",
      "unit_price": 3.20,
      "available": true
    }}
  }},
  "best_price_supplier": "name of cheapest supplier",
  "best_price": 2.85,
  "highest_price": 3.20
}}

If an item only appears in one supplier, still include it with only that supplier in supplier_data.
Return the JSON array only:"""

    msg = client.messages.create(
        model='claude-sonnet-4-20250514',
        max_tokens=8000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    text = msg.content[0].text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    return json.loads(text)


def _build_summary(session):
    items = session.items.all()
    total_best = sum(float(i.best_price or 0) * float(i.quantity or 1) for i in items)
    total_highest = sum(float(i.highest_price or 0) * float(i.quantity or 1) for i in items)
    total_customer = sum(float(i.customer_price or 0) * float(i.quantity or 1) for i in items)
    return {
        'total_if_best': round(total_best, 2),
        'total_if_highest': round(total_highest, 2),
        'total_customer_price': round(total_customer, 2),
        'saving_vs_highest': round(total_highest - total_best, 2),
        'profit': round(total_customer - total_best, 2),
        'item_count': len(items),
    }


@bp.route('/job/<int:job_card_id>/sessions')
@login_required
@require_full_mode
def job_sessions(job_card_id):
    sessions = SupplierQuoteSession.query.filter_by(
        user_id=current_user.id,
        job_card_id=job_card_id
    ).order_by(SupplierQuoteSession.created_at.desc()).all()
    return jsonify({'sessions': [{
        'id': s.id, 'name': s.name, 'status': s.status,
        'quote_count': s.quote_count, 'item_count': s.item_count,
    } for s in sessions]})
