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


@bp.route('/api/upload/quota', methods=['GET'])
@login_required
def check_quota():
    """Check user's remaining invoice quota"""
    remaining = current_user.invoices_remaining
    can_upload = current_user.can_upload_invoice
    
    return jsonify({
        'can_upload': can_upload,
        'remaining': remaining if remaining != float('inf') else 'unlimited',
        'is_unlimited': remaining == float('inf'),
        'bonus_invoices': current_user.bonus_invoices or 0,
        'plan': current_user.subscription_plan
    })


@bp.route('/api/upload/single', methods=['POST'])
@login_required
def api_upload_single():
    """Handle single file upload - called sequentially from frontend"""
    try:
        # Check quota BEFORE processing
        if not current_user.can_upload_invoice:
            remaining = current_user.invoices_remaining
            if remaining == 0:
                return jsonify({
                    'error': 'Invoice quota exceeded',
                    'quota_exceeded': True,
                    'message': 'You have used all your invoices for this billing period. Upgrade to Pro for unlimited invoices or purchase additional invoices.',
                    'remaining': 0
                }), 403
            else:
                return jsonify({
                    'error': 'No active subscription',
                    'message': 'Please subscribe to continue processing invoices.'
                }), 403
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        document_type = request.form.get('document_type', 'invoice')
        
        if not file or not file.filename:
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        from app.parsers.parser_service import InvoiceParserService
        from app.extensions import db
        
        master_parser = InvoiceParserService()
        
        # Get user markup settings
        user_markup_settings = {
            'is_admin': current_user.is_admin,
            'default_markup': current_user.default_markup or 50.0
        }
        
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join('temp_uploads', f"{timestamp}_{filename}")
        
        os.makedirs('temp_uploads', exist_ok=True)
        file.save(filepath)
        
        try:
            # Parse invoice(s) - may return multiple for consolidated PDFs
            parsed_invoices = master_parser.parse(
                filepath, 
                use_claude=True, 
                document_type=document_type,
                user_markup_settings=user_markup_settings
            )
            
            results = []
            errors = []
            
            for invoice_data in parsed_invoices:
                if invoice_data.get('success'):
                    # Check quota again before saving each invoice
                    if not current_user.can_upload_invoice:
                        errors.append('Quota exceeded - some invoices not saved')
                        break
                    
                    # Save to database
                    saved_invoice = save_invoice_to_db(
                        invoice_data, 
                        filename, 
                        current_user.id,
                        document_type
                    )
                    
                    # Use quota (deducts from bonus if needed)
                    current_user.use_invoice_quota(1)
                    db.session.commit()
                    
                    # Prepare result for frontend
                    items = invoice_data.get('items', [])
                    total = sum(item.get('total_amount', 0) for item in items)
                    
                    result = {
                        'id': saved_invoice.id,
                        'filename': filename,
                        'supplier': invoice_data.get('supplier', 'Unknown'),
                        'items_count': len(items),
                        'total': total,
                        'job_reference': invoice_data.get('job_reference'),
                        'items': items[:5],
                        'all_items': items,
                        'expanded': False,
                        'success': True,
                        'method': invoice_data.get('method'),
                        'confidence': invoice_data.get('confidence'),
                        'needs_review': invoice_data.get('needs_review', False),
                        'comparison': invoice_data.get('comparison'),
                        'saved': True
                    }
                    
                    if invoice_data.get('consolidated'):
                        result['consolidated'] = True
                        result['order_number'] = invoice_data.get('order_number')
                        result['total_orders'] = invoice_data.get('total_orders')
                    
                    results.append(result)
                else:
                    errors.append(invoice_data.get('error', 'Unknown error'))
            
            # Clean up temp file
            if os.path.exists(filepath):
                os.remove(filepath)
            
            if results:
                return jsonify({
                    'success': True,
                    'processed': len(results),
                    'results': results,
                    'errors': errors if errors else [],
                    'remaining': current_user.invoices_remaining if current_user.invoices_remaining != float('inf') else 'unlimited'
                })
            else:
                error_message = errors[0] if errors else 'No invoices processed'
                return jsonify({
                    'error': error_message,
                    'details': errors
                }), 400
                
        finally:
            # Ensure temp file cleanup
            if os.path.exists(filepath):
                os.remove(filepath)
                
    except Exception as e:
        current_app.logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    """Handle file upload - legacy endpoint for backward compatibility"""
    try:
        current_app.logger.info("=== UPLOAD REQUEST ===")
        
        # Check quota BEFORE processing
        if not current_user.can_upload_invoice:
            return jsonify({
                'error': 'Invoice quota exceeded. Please upgrade your plan or purchase additional invoices.',
                'quota_exceeded': True
            }), 403
        
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        use_claude = request.form.get('use_claude', 'true').lower() == 'true'
        document_type = request.form.get('document_type', 'invoice')
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files selected'}), 400
        
        # Check if user has enough quota for all files
        remaining = current_user.invoices_remaining
        if remaining != float('inf') and len(files) > remaining:
            return jsonify({
                'error': f'You can only process {remaining} more invoice(s) this period. You selected {len(files)} files.',
                'quota_exceeded': True,
                'remaining': remaining
            }), 403
        
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
                # Re-check quota before each file
                if not current_user.can_upload_invoice:
                    errors.append(f"{file.filename}: Quota exceeded")
                    continue
                
                try:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filepath = os.path.join('temp_uploads', f"{timestamp}_{filename}")
                    
                    os.makedirs('temp_uploads', exist_ok=True)
                    file.save(filepath)
                    
                    # Parse invoice(s) - returns LIST
                    parsed_invoices = master_parser.parse(
                        filepath, 
                        use_claude=use_claude, 
                        document_type=document_type,
                        user_markup_settings=user_markup_settings
                    )
                    
                    # Save each invoice to database
                    for invoice_data in parsed_invoices:
                        if invoice_data.get('success'):
                            # Check quota again
                            if not current_user.can_upload_invoice:
                                errors.append(f"{filename}: Quota exceeded")
                                break
                            
                            # Save to database
                            saved_invoice = save_invoice_to_db(
                                invoice_data, 
                                filename, 
                                current_user.id,
                                document_type
                            )
                            
                            # Use quota
                            current_user.use_invoice_quota(1)
                            db.session.commit()
                            
                            # Prepare result for frontend
                            items = invoice_data.get('items', [])
                            total = sum(item.get('total_amount', 0) for item in items)
                            
                            result = {
                                'id': saved_invoice.id,
                                'filename': filename,
                                'supplier': invoice_data.get('supplier', 'Unknown'),
                                'items_count': len(items),
                                'total': total,
                                'job_reference': invoice_data.get('job_reference'),
                                'items': items[:5],
                                'all_items': items,
                                'expanded': False,
                                'success': True,
                                'method': invoice_data.get('method'),
                                'confidence': invoice_data.get('confidence'),
                                'needs_review': invoice_data.get('needs_review', False),
                                'comparison': invoice_data.get('comparison'),
                                'saved': True
                            }
                            
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
                'errors': errors if errors else [],
                'remaining': current_user.invoices_remaining if current_user.invoices_remaining != float('inf') else 'unlimited'
            })
        else:
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
