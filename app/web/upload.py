"""Upload routes"""
from flask import Blueprint, render_template, request, jsonify
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
    """Handle file upload and process invoices"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        supplier = request.form.get('supplier', 'auto')
        
        if not files:
            return jsonify({'error': 'No files selected'}), 400
        
        results = []
        errors = []
        
        # Import parsers
        from app.parsers.yesss_parser import YesssInvoiceParser
        from app.parsers.wholesale_parser import WholesaleInvoiceParser
        from app.parsers.cef_parser import CEFInvoiceParser
        
        for file in files:
            if file and allowed_file(file.filename):
                try:
                    # Save file temporarily
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{filename}"
                    filepath = os.path.join('temp_uploads', unique_filename)
                    
                    # Ensure directory exists
                    os.makedirs('temp_uploads', exist_ok=True)
                    
                    file.save(filepath)
                    
                    # Auto-detect supplier or use selected one
                    parser = None
                    detected_supplier = None
                    
                    if supplier == 'auto' or supplier == 'yesss':
                        yesss_parser = YesssInvoiceParser()
                        if yesss_parser.detect(filepath):
                            parser = yesss_parser
                            detected_supplier = 'YESSS Electrical'
                    
                    if not parser and (supplier == 'auto' or supplier == 'wholesale'):
                        wholesale_parser = WholesaleInvoiceParser()
                        if wholesale_parser.detect(filepath):
                            parser = wholesale_parser
                            detected_supplier = 'Wholesale Electrics'
                    
                    if not parser and (supplier == 'auto' or supplier == 'cef'):
                        cef_parser = CEFInvoiceParser()
                        if cef_parser.detect(filepath):
                            parser = cef_parser
                            detected_supplier = 'CEF'
                    
                    if parser:
                        # Parse the invoice
                        parsed_data = parser.parse(filepath)
                        
                        results.append({
                            'filename': filename,
                            'supplier': detected_supplier,
                            'items_count': len(parsed_data.get('items', [])),
                            'total': parsed_data.get('total', 0),
                            'items': parsed_data.get('items', [])[:5],  # First 5 items for preview
                            'success': True
                        })
                    else:
                        errors.append(f"{filename}: Could not detect supplier")
                    
                    # Clean up temp file
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
                except Exception as e:
                    errors.append(f"{filename}: {str(e)}")
            else:
                errors.append(f'{file.filename} is not a valid PDF file')
        
        if results:
            return jsonify({
                'success': True,
                'processed': len(results),
                'results': results,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'error': 'No invoices could be processed',
                'details': errors
            }), 400
            
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500
