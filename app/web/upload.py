"""Upload routes - handles single and consolidated invoices"""
from flask import Blueprint, render_template, request, jsonify, current_app
from werkzeug.utils import secure_filename
import os
from datetime import datetime

bp = Blueprint('upload', __name__)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/upload')
def upload_page():
    """Upload page"""
    return render_template('upload/index.html')

@bp.route('/api/upload', methods=['POST'])
def api_upload():
    """Handle file upload and process invoices - supports consolidated invoices"""
    try:
        current_app.logger.info("=== UPLOAD REQUEST ===")
        
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        use_claude = request.form.get('use_claude', 'true').lower() == 'true'
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files selected'}), 400
        
        results = []
        errors = []
        
        from app.parsers.parser_service import InvoiceParserService
        master_parser = InvoiceParserService()
        
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                try:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filepath = os.path.join('temp_uploads', f"{timestamp}_{filename}")
                    
                    os.makedirs('temp_uploads', exist_ok=True)
                    file.save(filepath)
                    
                    # Parser now returns LIST of invoices (for consolidated support)
                    parsed_invoices = master_parser.parse(filepath, use_claude=use_claude)
                    
                    # Process each invoice (could be 1 for single, or multiple for consolidated)
                    for invoice_data in parsed_invoices:
                        if invoice_data.get('success'):
                            items = invoice_data.get('items', [])
                            total = sum(item.get('total_amount', 0) for item in items)
                            
                            result = {
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
                                'comparison': invoice_data.get('comparison')
                            }
                            
                            # Add consolidated metadata if present
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
            return jsonify({
                'error': 'No invoices processed',
                'details': errors
            }), 400
            
    except Exception as e:
        current_app.logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500
