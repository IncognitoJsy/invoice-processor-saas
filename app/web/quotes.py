"""Quotes routes - view and manage saved quotes"""
from flask import Blueprint, render_template, jsonify, request, Response
from flask_login import login_required, current_user
from datetime import datetime
import csv
import io

bp = Blueprint('quotes', __name__)


@bp.route('/quotes')
@login_required
def quotes_page():
    """Quotes listing page"""
    return render_template('quotes/index.html')


@bp.route('/api/quotes')
@login_required
def get_quotes():
    """Get all quotes for current user"""
    from app.models.invoice import Invoice
    
    # Filter by document_type = 'quote'
    quotes = Invoice.query.filter_by(user_id=current_user.id, document_type='quote')\
        .order_by(Invoice.created_at.desc())\
        .all()
    
    # Calculate stats
    total_cost = sum(float(q.total_cost or 0) for q in quotes)
    total_selling = sum(float(q.total_selling or 0) for q in quotes)
    total_profit = sum(float(q.total_profit or 0) for q in quotes)
    
    # Get unique suppliers
    suppliers = list(set(q.supplier_name for q in quotes if q.supplier_name))
    suppliers.sort()
    
    return jsonify({
        'success': True,
        'quotes': [q.to_dict() for q in quotes],
        'stats': {
            'total_quotes': len(quotes),
            'total_cost': total_cost,
            'total_selling': total_selling,
            'total_profit': total_profit
        },
        'suppliers': suppliers
    })


@bp.route('/api/quotes/<int:quote_id>')
@login_required
def get_quote(quote_id):
    """Get single quote with items"""
    from app.models.invoice import Invoice, InvoiceItem
    
    quote = Invoice.query.filter_by(id=quote_id, user_id=current_user.id, document_type='quote').first()
    
    if not quote:
        return jsonify({'success': False, 'error': 'Quote not found'}), 404
    
    items = InvoiceItem.query.filter_by(invoice_id=quote.id).all()
    
    return jsonify({
        'success': True,
        'quote': {
            **quote.to_dict(),
            'items': [item.to_dict() for item in items]
        }
    })


@bp.route('/api/quotes/<int:quote_id>', methods=['DELETE'])
@login_required
def delete_quote(quote_id):
    """Delete a quote"""
    from app.models.invoice import Invoice
    from app.extensions import db
    
    quote = Invoice.query.filter_by(id=quote_id, user_id=current_user.id, document_type='quote').first()
    
    if not quote:
        return jsonify({'success': False, 'error': 'Quote not found'}), 404
    
    db.session.delete(quote)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Quote deleted'})


@bp.route('/api/quotes/export')
@login_required
def export_quotes():
    """Export quotes to CSV"""
    from app.models.invoice import Invoice, InvoiceItem
    
    quotes = Invoice.query.filter_by(user_id=current_user.id, document_type='quote')\
        .order_by(Invoice.created_at.desc())\
        .all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header row
    writer.writerow([
        'Date', 'Supplier', 'Quote Number', 'Job Reference',
        'Part Number', 'Description', 'Quantity',
        'Cost Each', 'Cost Total', 'Selling Each', 'Selling Total',
        'Profit Each', 'Profit Total', 'QB Estimate ID'
    ])
    
    # Data rows
    for quote in quotes:
        items = InvoiceItem.query.filter_by(invoice_id=quote.id).all()
        
        for item in items:
            writer.writerow([
                quote.created_at.strftime('%Y-%m-%d') if quote.created_at else '',
                quote.supplier_name or '',
                quote.invoice_number or '',
                quote.job_reference or '',
                item.part_number or '',
                item.description or '',
                float(item.quantity or 0),
                float(item.cost_per_item or 0),
                float(item.total_amount or 0),
                float(item.selling_price or 0),
                float(item.selling_price or 0) * float(item.quantity or 0),
                float(item.profit_per_item or 0),
                float(item.profit_per_item or 0) * float(item.quantity or 0),
                quote.qb_estimate_id or ''
            ])
    
    # Prepare response
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=quotes_{datetime.now().strftime("%Y%m%d")}.csv'
        }
    )
