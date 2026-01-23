"""API routes for part number corrections and invoice item updates"""
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.invoice import Invoice, InvoiceItem
from app.models.part_number_correction import PartNumberCorrection
import logging

logger = logging.getLogger(__name__)

# Create blueprint - add this to your existing api blueprint or create new one
part_number_bp = Blueprint('part_numbers', __name__, url_prefix='/api')


@part_number_bp.route('/invoice-items/<int:item_id>/part-number', methods=['PUT'])
@login_required
def update_part_number(item_id):
    """
    Update a part number for an invoice item.
    If the part number was changed from what Claude extracted, save the correction for learning.
    """
    try:
        # Get the invoice item
        item = InvoiceItem.query.get_or_404(item_id)
        
        # Verify user owns this invoice
        invoice = Invoice.query.get(item.invoice_id)
        if not invoice or invoice.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json()
        new_part_number = data.get('part_number', '').strip()
        
        if not new_part_number:
            return jsonify({'error': 'Part number is required'}), 400
        
        old_part_number = item.part_number
        
        # Update the item
        item.part_number = new_part_number
        db.session.commit()
        
        # If part number changed, save correction for learning
        correction_saved = None
        if old_part_number and old_part_number.upper() != new_part_number.upper():
            correction = PartNumberCorrection.add_or_update_correction(
                user_id=current_user.id,
                original_ocr=old_part_number,
                corrected_part=new_part_number,
                supplier_name=invoice.supplier_name,
                invoice_id=invoice.id
            )
            if correction:
                correction_saved = correction.to_dict()
                logger.info(f"Learned correction: '{old_part_number}' -> '{new_part_number}' for supplier {invoice.supplier_name}")
        
        return jsonify({
            'success': True,
            'item': item.to_dict(),
            'correction_learned': correction_saved is not None,
            'correction': correction_saved,
            'message': f"Part number updated{' and correction learned' if correction_saved else ''}"
        })
        
    except Exception as e:
        logger.error(f"Error updating part number: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@part_number_bp.route('/invoice-items/<int:item_id>', methods=['PUT'])
@login_required
def update_invoice_item(item_id):
    """
    Update any field on an invoice item (part_number, description, quantity, etc.)
    """
    try:
        item = InvoiceItem.query.get_or_404(item_id)
        
        # Verify user owns this invoice
        invoice = Invoice.query.get(item.invoice_id)
        if not invoice or invoice.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        data = request.get_json()
        old_part_number = item.part_number
        
        # Update allowed fields
        if 'part_number' in data:
            item.part_number = data['part_number'].strip()
        if 'description' in data:
            item.description = data['description']
        if 'quantity' in data:
            item.quantity = float(data['quantity'])
        if 'cost_per_item' in data:
            item.cost_per_item = float(data['cost_per_item'])
        if 'selling_price' in data:
            item.selling_price = float(data['selling_price'])
        
        # Recalculate totals
        item.total_amount = float(item.quantity) * float(item.cost_per_item)
        if item.selling_price:
            item.profit_per_item = float(item.selling_price) - float(item.cost_per_item)
        
        db.session.commit()
        
        # Learn part number correction if changed
        correction_saved = None
        if 'part_number' in data and old_part_number:
            new_part_number = data['part_number'].strip()
            if old_part_number.upper() != new_part_number.upper():
                correction = PartNumberCorrection.add_or_update_correction(
                    user_id=current_user.id,
                    original_ocr=old_part_number,
                    corrected_part=new_part_number,
                    supplier_name=invoice.supplier_name,
                    invoice_id=invoice.id
                )
                if correction:
                    correction_saved = correction.to_dict()
        
        # Recalculate invoice totals
        _recalculate_invoice_totals(invoice)
        
        return jsonify({
            'success': True,
            'item': item.to_dict(),
            'invoice': invoice.to_dict(),
            'correction_learned': correction_saved is not None
        })
        
    except Exception as e:
        logger.error(f"Error updating invoice item: {str(e)}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@part_number_bp.route('/part-number-corrections', methods=['GET'])
@login_required
def get_corrections():
    """Get all learned part number corrections for current user"""
    try:
        supplier = request.args.get('supplier')
        
        query = PartNumberCorrection.query.filter_by(
            user_id=current_user.id,
            is_active=True
        )
        
        if supplier:
            query = query.filter(
                (PartNumberCorrection.supplier_name == supplier) |
                (PartNumberCorrection.supplier_name == None)
            )
        
        corrections = query.order_by(PartNumberCorrection.times_applied.desc()).all()
        
        return jsonify({
            'corrections': [c.to_dict() for c in corrections],
            'count': len(corrections)
        })
        
    except Exception as e:
        logger.error(f"Error fetching corrections: {str(e)}")
        return jsonify({'error': str(e)}), 500


@part_number_bp.route('/part-number-corrections/<int:correction_id>', methods=['DELETE'])
@login_required
def delete_correction(correction_id):
    """Delete/disable a learned correction"""
    try:
        correction = PartNumberCorrection.query.get_or_404(correction_id)
        
        if correction.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Soft delete - just disable
        correction.is_active = False
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Correction removed'
        })
        
    except Exception as e:
        logger.error(f"Error deleting correction: {str(e)}")
        return jsonify({'error': str(e)}), 500


@part_number_bp.route('/quickbooks/products/search', methods=['GET'])
@login_required
def search_quickbooks_products():
    """Search QuickBooks products for autocomplete suggestions"""
    try:
        query = request.args.get('q', '').strip().upper()
        
        if len(query) < 2:
            return jsonify({'products': []})
        
        # Get QuickBooks connection
        from app.models.quickbooks import QuickBooksConnection
        from app.integrations.quickbooks_service import QuickBooksService
        
        qb_connection = QuickBooksConnection.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not qb_connection:
            return jsonify({'products': [], 'message': 'QuickBooks not connected'})
        
        qb_service = QuickBooksService()
        response = qb_service.get_items(qb_connection)
        
        if not response or 'error' in response:
            return jsonify({'products': []})
        
        items = response.get('QueryResponse', {}).get('Item', [])
        
        # Filter and format matching products
        matches = []
        for item in items:
            sku = item.get('Sku', '') or ''
            name = item.get('Name', '') or ''
            
            if query in sku.upper() or query in name.upper():
                matches.append({
                    'sku': sku,
                    'name': name,
                    'id': item.get('Id')
                })
                
                if len(matches) >= 10:  # Limit results
                    break
        
        return jsonify({'products': matches})
        
    except Exception as e:
        logger.error(f"Error searching products: {str(e)}")
        return jsonify({'products': [], 'error': str(e)})


def _recalculate_invoice_totals(invoice):
    """Recalculate invoice totals after item changes"""
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    
    total_cost = sum(float(item.total_amount) for item in items)
    total_selling = sum(float(item.selling_price or 0) * float(item.quantity) for item in items)
    total_profit = total_selling - total_cost
    
    invoice.total_cost = total_cost
    invoice.total_selling = total_selling
    invoice.total_profit = total_profit
    invoice.items_count = len(items)
    
    if total_cost > 0:
        invoice.average_markup = ((total_selling - total_cost) / total_cost) * 100
    
    db.session.commit()
