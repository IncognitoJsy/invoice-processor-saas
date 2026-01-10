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
                    
                    parsed_data = master_parser.parse(filepath, use_claude=use_claude)
                    
                    if parsed_data.get('success'):
                        items = parsed_data.get('items', [])
                        total = sum(item.get('total_amount', 0) for item in items)
                        
                        results.append({
                            'filename': filename,
                            'supplier': parsed_data.get('supplier', 'Unknown'),
                            'items_count': len(items),
                            'total': total,
                            'job_reference': parsed_data.get('job_reference'),
                            'items': items[:5],
                            'all_items': items,
                            'expanded': False,
                            'success': True,
                            'method': parsed_data.get('method'),
                            'confidence': parsed_data.get('confidence'),
                            'needs_review': parsed_data.get('needs_review', False),
                            'comparison': parsed_data.get('comparison')
                        })
                    else:
                        errors.append(f"{filename}: {parsed_data.get('error')}")
                    
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
                except Exception as e:
                    current_app.logger.error(f"Error: {str(e)}", exc_info=True)
                    errors.append(f"{filename}: {str(e)}")
        
        if results:
            return jsonify({'success': True, 'processed': len(results), 'results': results, 'errors': errors})
        else:
            return jsonify({'error': 'No invoices processed', 'details': errors}), 400
            
    except Exception as e:
        current_app.logger.error(f"Server error: {str(e)}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500