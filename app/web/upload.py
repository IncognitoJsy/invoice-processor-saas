"""Upload routes"""
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
    """Handle file upload and process invoices"""
    try:
        current_app.logger.info("=== UPLOAD REQUEST RECEIVED ===")
        current_app.logger.info(f"Files in request: {request.files}")
        
        if 'files' not in request.files:
            current_app.logger.error("No files key in request.files")
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        supplier = request.form.get('supplier', 'auto')
        
        current_app.logger.info(f"Number of files: {len(files)}")
        
        if not files or len(files) == 0:
            return jsonify({'error': 'No files selected'}), 400
        
        results = []
        errors = []
        
        from app.parsers.yesss_parser import YesssInvoiceParser
        from app.parsers.wholesale_parser import WholesaleInvoiceParser
        from app.parsers.cef_parser import CEFInvoiceParser
        
        for file in files:
            current_app.logger.info(f"Processing: {file.filename}")
            
            if file and file.filename and allowed_file(file.filename):
                try:
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    unique_filename = f"{timestamp}_{filename}"
                    filepath = os.path.join('temp_uploads', unique_filename)
                    
                    os.makedirs('temp_uploads', exist_ok=True)
                    file.save(filepath)
                    
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
                    
                    current_app.logger.info(f"Parser result: {parser}")
                    current_app.logger.info(f"Detected supplier: {detected_supplier}")
                    
                    if parser:
                        current_app.logger.info("Starting parse...")
                        parsed_data = parser.parse(filepath)
                        current_app.logger.info(f"Parse complete: {parsed_data}")
                        
                        results.append({
                            'filename': filename,
                            'supplier': detected_supplier,
                            'items_count': len(parsed_data.get('items', [])),
                            'total': parsed_data.get('total', 0),
                            'items': parsed_data.get('items', [])[:5],
                            'success': True
                        })
                    else:
                        errors.append(f"{filename}: Could not detect supplier")
                    
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
                except Exception as e:
                    current_app.logger.error(f"Error: {str(e)}", exc_info=True)
                    errors.append(f"{filename}: {str(e)}")
            else:
                errors.append(f'{file.filename if file and file.filename else "Unknown"} is not a valid PDF')
        
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
        current_app.logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500
