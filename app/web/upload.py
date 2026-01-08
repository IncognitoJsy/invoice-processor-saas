"""Upload routes"""
from flask import Blueprint, render_template, request, jsonify
from werkzeug.utils import secure_filename
import os

bp = Blueprint('upload', __name__)

@bp.route('/upload')
def upload_page():
    """Upload page"""
    return render_template('upload/index.html')

@bp.route('/api/upload', methods=['POST'])
def api_upload():
    """Handle file upload"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        supplier = request.form.get('supplier', 'auto')
        
        processed = 0
        errors = []
        
        for file in files:
            if file and file.filename.endswith('.pdf'):
                filename = secure_filename(file.filename)
                # TODO: Process the invoice
                processed += 1
            else:
                errors.append(f'{file.filename} is not a PDF')
        
        if processed > 0:
            return jsonify({
                'success': True,
                'processed': processed,
                'errors': errors if errors else None
            })
        else:
            return jsonify({'error': 'No valid PDF files found'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
