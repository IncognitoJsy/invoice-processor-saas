"""Upload routes - handles file upload and saves to database"""
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from decimal import Decimal

bp = Blueprint('upload', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/upload')
@login_required
def upload_page():
    """Upload page"""
    return render_template('upload/index.html')

@bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    """Handle file upload, process invoices, and save to database"""
    try:
        current_app.logger.info("=== UPLOAD REQUEST ===")
        
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        use_claude = request.form.get('use_claude', 'true').lower() == 'true'
        document_type = request.form.get('document_type', 'invoice')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files selected'}), 400
        
        results = []
        errors = []
        
        from app.parsers.parser_service import InvoiceParserService
        from app.models.invoice import Invoice, InvoiceItem
        from app.extensions import db
        
        master_parser = InvoiceParserService()
        
        # Get user markup settings to pass to parser
        user_markup_settings = {
            'is_admin': current_user.is_admin,
            'default_markup': current_user.default_markup or 50.0
        }
        current_app.logger.info(f"User markup settings: admin={user_markup_settings['is_admin']}, markup={user_markup_settings['default_markup']}%")
        
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                try:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filepath = os.path.join('temp_uploads', f"{timestamp}_{filename}")
                    
                    os.makedirs('temp_uploads', exist_ok=True)
                    file.save(filepath)
                    
                    # Parse invoice(s) - returns LIST, now with user markup settings
                    parsed_invoices = master_parser.parse(
                        filepath, 
                        use_claude=use_claude, 
                        document_type=document_type,
                        user_markup_settings=user_markup_settings
                    )
                    
                    # Save each invoice to database
                    for invoice_data in parsed_invoices:
                        if invoice_data.get('success'):
                            # Save to database
                            saved_invoice = save_invoice_to_db(
                                invoice_data, 
                                filename, 
                                current_user.id,
                                document_type
                            )
                            
                            # Prepare result for frontend
                            items = invoice_data.get('items', [])
                            total = sum(item.get('total_amount', 0) for item in items)
                            
                            result = {
                                'id': saved_invoice.id,  # Database ID
                                'filename': filename,
                                'supplier': invoice_data.get('supplier', 'Unknown'),
                                'items_count': len(items),
                                'total': total,
                                'job_reference': invoice_data.get('job_reference'),
                                'items': items[:5],  # First 5 for preview
                                'all_items': items,  # All items for expansion
                                'expanded': False,
                                'success': True,
                                'method': invoice_data.get('method'),
                                'confidence': invoice_data.get('confidence'),
                                'needs_review': invoice_data.get('needs_review', False),
                                'comparison': invoice_data.get('comparison'),
                                'saved': True  # Indicate it's saved to DB
                            }
                            
                            # Add consolidated metadata
                            if invoice_data.get('consolidated'):
                                result['consolidated'] = True
                                result['order_number'] = invoice_data.get('order_number')
                                result['total_orders'] = invoice_data.get('total_orders')
                            
                            results.append(result)
                        else:
                            errors.append(f"{filename}: {invoice_data.get('error')}")
                    
                    # Clean up temp file
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
                except Exception as e:
                    current_app.logger.error(f"Error processing {filename}: {str(e)}", exc_info=True)
                    errors.append(f"{filename}: {str(e)}")
        
        if results:
            return jsonify({
                'success': True,
                'processed': len(results),
                'results': results,
                'errors': errors if errors else []
            })
        else:
            # Return the first specific error if available
            error_message = errors[0] if errors else 'No invoices processed'
            return jsonify({
                'error': error_message,
                'details': errors
            }), 400
            
    except Exception as e:
        current_app.logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500


def save_invoice_to_db(invoice_data, filename, user_id, document_type='invoice'):
    """Save parsed invoice and items to database"""
    from app.models.invoice import Invoice, InvoiceItem
    from app.extensions import db
    
    items = invoice_data.get('items', [])
    
    # Calculate totals
    total_cost = sum(Decimal(str(item.get('total_amount', 0))) for item in items)
    total_selling = sum(
        Decimal(str(item.get('selling_price', 0))) * Decimal(str(item.get('quantity', 0))) 
        for item in items
    )
    total_profit = sum(
        Decimal(str(item.get('profit_per_item', 0))) * Decimal(str(item.get('quantity', 0))) 
        for item in items
    )
    
    # Calculate average markup
    avg_markup = None
    if total_cost > 0:
        avg_markup = ((total_selling - total_cost) / total_cost) * 100
    
    # Create invoice record
    invoice = Invoice(
        user_id=user_id,
        document_type=document_type,
        supplier_name=invoice_data.get('supplier', 'Unknown'),
        invoice_number=invoice_data.get('invoice_number'),
        job_reference=invoice_data.get('job_reference'),
        pdf_filename=filename,
        is_consolidated=invoice_data.get('consolidated', False),
        order_number=invoice_data.get('order_number'),
        total_orders=invoice_data.get('total_orders'),
        total_cost=total_cost,
        total_selling=total_selling,
        total_profit=total_profit,
        average_markup=avg_markup,
        items_count=len(items),
        parser_method=invoice_data.get('method'),
        confidence=invoice_data.get('confidence'),
        needs_review=invoice_data.get('needs_review', False),
        status='completed',
        processed_at=datetime.utcnow()
    )
    
    db.session.add(invoice)
    db.session.flush()  # Get invoice.id
    
    # Create invoice items
    for item_data in items:
        item = InvoiceItem(
            invoice_id=invoice.id,
            part_number=item_data.get('part_number'),
            description=item_data.get('description'),
            quantity=Decimal(str(item_data.get('quantity', 0))),
            original_unit_price=Decimal(str(item_data.get('original_unit_price', 0))),
            discount_percent=Decimal(str(item_data.get('discount', 0))) if item_data.get('discount') else None,
            cost_per_item=Decimal(str(item_data.get('cost_per_item', 0))),
            total_amount=Decimal(str(item_data.get('total_amount', 0))),
            selling_price=Decimal(str(item_data.get('selling_price', 0))),
            markup_percent=Decimal(str(item_data.get('markup_percent', 0))),
            profit_per_item=Decimal(str(item_data.get('profit_per_item', 0)))
        )
        db.session.add(item)
    
    db.session.commit()
    
    current_app.logger.info(f"✅ Saved invoice {invoice.id} with {len(items)} items to database")
    
    return invoice
