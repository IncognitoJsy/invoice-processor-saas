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
    return render_template('invoices/index.html')


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
    from app.extensions import db
    
    invoice = Invoice.query.filter_by(id=invoice_id, user_id=current_user.id).first()
    
    if not invoice:
        return jsonify({'success': False, 'error': 'Invoice not found'}), 404
    
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
