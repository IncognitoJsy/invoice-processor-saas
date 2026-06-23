"""Invoices routes - view and manage saved invoices"""
from flask import Blueprint, render_template, jsonify, request, Response
from flask_login import login_required, current_user
from datetime import datetime
import csv
import io

bp = Blueprint('invoices', __name__)


@bp.route('/invoices')
@login_required
def invoices_page():
    """Invoices listing page"""
    from app.models.customer import Customer
    mode = current_user.platform_mode or 'sync'
    customers = []
    if mode in ['full', 'both']:
        customers = Customer.query.filter_by(user_id=current_user.id)            .order_by(Customer.name.asc()).all()
        customers = [{'id': c.id, 'name': c.display_name, 'email': c.email or ''} for c in customers]
    return render_template('invoices/index.html',
        platform_mode=mode,
        customers=customers
    )


@bp.route('/api/invoices')
@login_required
def get_invoices():
    """Get all invoices for current user"""
    from app.models.invoice import Invoice
    
    invoices = Invoice.query.filter_by(user_id=current_user.id)\
        .order_by(Invoice.created_at.desc())\
        .all()
    
    # Calculate stats
    total_cost = sum(float(inv.total_cost or 0) for inv in invoices)
    total_selling = sum(float(inv.total_selling or 0) for inv in invoices)
    total_profit = sum(float(inv.total_profit or 0) for inv in invoices)
    
    # Get unique suppliers
    suppliers = list(set(inv.supplier_name for inv in invoices if inv.supplier_name))
    suppliers.sort()
    
    return jsonify({
        'success': True,
        'invoices': [inv.to_dict() for inv in invoices],
        'stats': {
            'total_invoices': len(invoices),
            'total_cost': total_cost,
            'total_selling': total_selling,
            'total_profit': total_profit
        },
        'suppliers': suppliers
    })


@bp.route('/api/invoices/<int:invoice_id>')
@login_required
def get_invoice(invoice_id):
    """Get single invoice with items"""
    from app.models.invoice import Invoice, InvoiceItem
    
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    
    return jsonify({
        'success': True,
        'invoice': {
            **invoice.to_dict(),
            'items': [item.to_dict() for item in items]
        }
    })


@bp.route('/api/invoices/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_invoice(invoice_id):
    """Delete an invoice"""
    from app.models.invoice import Invoice
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
    # Clear any queue references to this invoice
    QueuedInvoice.query.filter_by(processed_invoice_id=invoice_id).update({'processed_invoice_id': None})
    
    db.session.delete(invoice)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Invoice deleted'})


@bp.route('/api/invoices/export')
@login_required
def export_invoices():
    """Export invoices to CSV"""
    from app.models.invoice import Invoice, InvoiceItem
    
    invoices = Invoice.query.filter_by(user_id=current_user.id)\
        .order_by(Invoice.created_at.desc())\
        .all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow([
        'Date', 'Supplier', 'Invoice Number', 'Job Reference',
        'Part Number', 'Description', 'Quantity',
        'Cost Each', 'Cost Total', 'Selling Each', 'Selling Total',
        'Profit Each', 'Profit Total'
    ])
    
    # Data rows
    for invoice in invoices:
        items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
        
        for item in items:
            writer.writerow([
                invoice.created_at.strftime('%Y-%m-%d') if invoice.created_at else '',
                invoice.supplier_name or '',
                invoice.invoice_number or '',
                invoice.job_reference or '',
                item.part_number or '',
                item.description or '',
                float(item.quantity or 0),
                float(item.cost_per_item or 0),
                float(item.total_amount or 0),
                float(item.selling_price or 0),
                float(item.selling_price or 0) * float(item.quantity or 0),
                float(item.profit_per_item or 0),
                float(item.profit_per_item or 0) * float(item.quantity or 0)
            ])
    
    # Prepare response
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=invoices_{datetime.now().strftime("%Y%m%d")}.csv'
        }
    )


@bp.route('/api/invoices/stats')
@login_required
def get_stats():
    """Get invoice statistics"""
    from app.models.invoice import Invoice
    from sqlalchemy import func
    
    # Overall stats
    stats = Invoice.query.filter_by(user_id=current_user.id)\
        .with_entities(
            func.count(Invoice.id).label('total'),
            func.sum(Invoice.total_cost).label('cost'),
            func.sum(Invoice.total_selling).label('selling'),
            func.sum(Invoice.total_profit).label('profit')
        ).first()
    
    # By supplier
    by_supplier = Invoice.query.filter_by(user_id=current_user.id)\
        .with_entities(
            Invoice.supplier_name,
            func.count(Invoice.id).label('count'),
            func.sum(Invoice.total_cost).label('cost')
        )\
        .group_by(Invoice.supplier_name)\
        .all()
    
    return jsonify({
        'success': True,
        'overall': {
            'total_invoices': stats.total or 0,
            'total_cost': float(stats.cost or 0),
            'total_selling': float(stats.selling or 0),
            'total_profit': float(stats.profit or 0)
        },
        'by_supplier': [
            {
                'supplier': s.supplier_name,
                'count': s.count,
                'cost': float(s.cost or 0)
            }
            for s in by_supplier
        ]
    })

@bp.route('/invoices/item/<int:item_id>/price', methods=['PUT'])
@login_required
def update_item_price(item_id):
    """Set or clear a line's MANUAL per-unit selling price.

      body {"selling_price": <num>}  -> manual override: price_overridden=True, selling = money(num)
      query ?reset=true              -> clear the override: revert to calculated_selling_price

    A manual override is DELIBERATE and BYPASSES the auto-calc retail cap (the cap only runs at
    parse time, in claude_parser._transform_items — it never re-runs here). markup_percent is
    recomputed from the new price so feature 2's "manual" badge shows the real manual markup.

    CONTRACT: any future "recalculate markup / re-price" action MUST skip rows where
    price_overridden is True (see InvoiceItem) — otherwise it silently destroys a deliberate price.
    """
    from app.models.invoice import Invoice, InvoiceItem
    from app.extensions import db
    from app.utils.money import money, to_decimal
    from decimal import Decimal

    item = InvoiceItem.query.get(item_id)
    if not item:
        return jsonify({'success': False, 'error': 'Item not found'}), 404

    invoice = Invoice.query.get(item.invoice_id)
    if not invoice or invoice.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    reset = request.args.get('reset', '').lower() in ('1', 'true', 'yes')
    if reset:
        # Revert to the auto-calculated price (which honoured the retail cap at parse time).
        item.selling_price = item.calculated_selling_price or item.selling_price
        item.price_overridden = False
    else:
        new_price = (request.get_json(silent=True) or {}).get('selling_price')
        if new_price is None:
            return jsonify({'success': False, 'error': 'Missing selling_price'}), 400
        price = money(to_decimal(new_price)) if to_decimal(new_price) is not None else None
        if price is None or price <= 0:
            return jsonify({'success': False, 'error': 'selling_price must be a number greater than 0'}), 400
        item.selling_price = price
        item.price_overridden = True

    # Recompute derived fields on the money-path standard (Decimal + money(), ROUND_HALF_UP).
    cost = to_decimal(item.cost_per_item) or Decimal('0')
    sell = to_decimal(item.selling_price) or Decimal('0')
    item.profit_per_item = money(sell - cost)
    if cost > 0:
        markup = money((sell - cost) / cost * 100)
        item.markup_percent = max(Decimal('-999.99'), min(markup, Decimal('999.99')))  # fit Numeric(5,2)
    else:
        item.markup_percent = Decimal('0')

    # Recalculate invoice totals (Decimal, line-authority).
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    invoice.total_selling = money(sum((to_decimal(i.selling_price or 0) * to_decimal(i.quantity or 0)
                                       for i in items), Decimal('0')))
    invoice.total_profit = money(sum((to_decimal(i.profit_per_item or 0) * to_decimal(i.quantity or 0)
                                      for i in items), Decimal('0')))

    db.session.commit()
    return jsonify({
        'success': True,
        'item': item.to_dict(),
        'invoice_totals': {
            'total_selling': float(invoice.total_selling),
            'total_profit': float(invoice.total_profit),
        },
    })


@bp.route('/api/invoices/<int:invoice_id>/assign-customer', methods=['POST'])
@login_required
def assign_customer(invoice_id):
    """Assign a processed invoice to a customer/job — full platform mode"""
    from app.models.invoice import Invoice
    from app.models.customer import Customer, Job
    from app.extensions import db

    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404

    data = request.get_json()
    customer_id = data.get('customer_id')
    job_id = data.get('job_id')

    if customer_id:
        customer = Customer.query.filter_by(id=customer_id, user_id=current_user.id).first()
        if not customer:
            return jsonify({'success': False, 'error': 'Customer not found'}), 404
        invoice.platform_customer_id = customer_id
        invoice.customer_match_confidence = 'manual'

    if job_id:
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        invoice.platform_job_id = job_id

    if not customer_id and not job_id:
        invoice.platform_customer_id = None
        invoice.platform_job_id = None
        invoice.customer_match_confidence = 'none'

    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/invoices/<int:invoice_id>/suggest-customer')
@login_required
def suggest_customer(invoice_id):
    """Auto-suggest customer based on job_reference fuzzy match"""
    from app.models.invoice import Invoice
    from app.models.customer import Customer, Job

    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404

    customers = Customer.query.filter_by(user_id=current_user.id).all()
    jobs = Job.query.filter_by(user_id=current_user.id).all()

    suggestions = []
    ref = (invoice.job_reference or '').lower().strip()

    if ref:
        for customer in customers:
            score = 0
            name = (customer.name or '').lower()
            company = (customer.company_name or '').lower()
            if ref in name or name in ref:
                score = 90
            elif ref in company or company in ref:
                score = 85
            elif any(word in name or word in company for word in ref.split() if len(word) > 2):
                score = 60
            if score > 0:
                suggestions.append({
                    'type': 'customer',
                    'id': customer.id,
                    'name': customer.display_name,
                    'email': customer.email,
                    'score': score
                })

        for job in jobs:
            score = 0
            title = (job.title or '').lower()
            jnum = (job.job_number or '').lower()
            if ref in title or title in ref:
                score = 95
            elif ref == jnum:
                score = 100
            elif any(word in title for word in ref.split() if len(word) > 2):
                score = 70
            if score > 0:
                customer_name = job.customer.display_name if job.customer else None
                suggestions.append({
                    'type': 'job',
                    'id': job.id,
                    'name': job.title,
                    'customer_id': job.customer_id,
                    'customer_name': customer_name,
                    'score': score
                })

    suggestions.sort(key=lambda x: x['score'], reverse=True)

    return jsonify({
        'success': True,
        'job_reference': invoice.job_reference,
        'current_customer_id': invoice.platform_customer_id,
        'current_job_id': invoice.platform_job_id,
        'suggestions': suggestions[:5],
        'customers': [{'id': c.id, 'name': c.display_name, 'email': c.email} for c in customers]
    })


@bp.route('/api/invoices/<int:invoice_id>/mark-reviewed', methods=['POST'])
@login_required
def mark_invoice_reviewed(invoice_id):
    """Clear an invoice's arithmetic-validation block after a human has checked it.

    Sets validation_errors back to NULL and lifts needs_review, allowing the
    invoice to sync to QuickBooks/Xero. Tenant-isolated by user_id.
    """
    from app.models.invoice import Invoice
    from app.extensions import db

    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404

    invoice.validation_errors = None
    invoice.needs_review = False
    db.session.commit()

    return jsonify({'success': True, 'message': 'Invoice marked as reviewed'})
