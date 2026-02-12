"""Queue management routes - PDF invoice stacking and drag-to-process"""
from flask import Blueprint, render_template, request, jsonify, current_app, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import hashlib

bp = Blueprint('queue', __name__, url_prefix='/queue')

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_queue_upload_path(user_id):
    """Get the upload path for queued files"""
    path = os.path.join('uploads', 'queue', str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def get_pdf_page_count(filepath):
    """Get page count of a PDF file"""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(filepath)
        return len(reader.pages)
    except Exception:
        return 1


def get_file_hash(filepath):
    """Generate SHA-256 hash of file content for deduplication"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


@bp.route('/')
@login_required
def index():
    """Queue page - shows stacked PDFs waiting to be processed"""
    return render_template('queue/index.html')


@bp.route('/api/list', methods=['GET'])
@login_required
def api_list_queue():
    """Get all queued invoices for the current user"""
    from app.models.queued_invoice import QueuedInvoice
    
    status_filter = request.args.get('status', 'queued')
    
    query = QueuedInvoice.query.filter_by(user_id=current_user.id)
    
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    items = query.order_by(QueuedInvoice.created_at.desc()).all()
    
    return jsonify({
        'success': True,
        'items': [item.to_dict() for item in items],
        'count': len(items)
    })


@bp.route('/api/upload', methods=['POST'])
@login_required
def api_upload_to_queue():
    """Upload one or more PDFs to the queue"""
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files')
    
    if not files or len(files) == 0:
        return jsonify({'error': 'No files selected'}), 400
    
    results = []
    errors = []
    upload_path = get_queue_upload_path(current_user.id)
    
    for file in files:
        if not file or not file.filename:
            continue
        
        if not allowed_file(file.filename):
            errors.append(f'{file.filename}: Only PDF and image files are allowed')
            continue
        
        try:
            original_filename = file.filename
            filename = secure_filename(original_filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            stored_filename = f"{timestamp}_{filename}"
            filepath = os.path.join(upload_path, stored_filename)
            
            file.save(filepath)
            
            # Get file info
            file_size = os.path.getsize(filepath)
            file_hash = get_file_hash(filepath)
            page_count = get_pdf_page_count(filepath) if filename.lower().endswith('.pdf') else 1
            
            # Check for duplicate (same file content already in queue)
            existing = QueuedInvoice.query.filter_by(
                user_id=current_user.id,
                attachment_hash=file_hash,
                status='queued'
            ).first()
            
            if existing:
                # Remove the duplicate file we just saved
                os.remove(filepath)
                errors.append(f'{original_filename}: Already in queue')
                continue
            
            # Create queue entry
            queued = QueuedInvoice(
                user_id=current_user.id,
                filename=stored_filename,
                original_filename=original_filename,
                file_path=filepath,
                file_size=file_size,
                page_count=page_count,
                source='manual',
                attachment_hash=file_hash,
                status='queued'
            )
            
            db.session.add(queued)
            db.session.flush()
            
            results.append(queued.to_dict())
            
        except Exception as e:
            current_app.logger.error(f"Error queueing {file.filename}: {str(e)}", exc_info=True)
            errors.append(f'{file.filename}: {str(e)}')
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'queued': len(results),
        'items': results,
        'errors': errors
    })


@bp.route('/api/<int:queue_id>/preview', methods=['GET'])
@login_required
def api_preview(queue_id):
    """Serve the queued PDF for preview"""
    from app.models.queued_invoice import QueuedInvoice
    
    item = QueuedInvoice.query.filter_by(id=queue_id, user_id=current_user.id).first()
    
    if not item:
        return jsonify({'error': 'Not found'}), 404
    
    if not os.path.exists(item.file_path):
        return jsonify({'error': 'File not found on disk'}), 404
    
    return send_file(
        item.file_path,
        mimetype='application/pdf' if item.filename.lower().endswith('.pdf') else 'image/*'
    )


@bp.route('/api/<int:queue_id>/process', methods=['POST'])
@login_required
def api_process_from_queue(queue_id):
    """Process a queued invoice - moves it to invoice or quote processing"""
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    item = QueuedInvoice.query.filter_by(id=queue_id, user_id=current_user.id).first()
    
    if not item:
        return jsonify({'error': 'Not found'}), 404
    
    if item.status != 'queued':
        return jsonify({'error': f'Item is already {item.status}'}), 400
    
    target_tab = request.json.get('target_tab', 'invoice')
    if target_tab not in ('invoice', 'quote'):
        return jsonify({'error': 'Invalid target tab'}), 400
    
    # Check quota before processing
    if not current_user.can_upload_invoice:
        return jsonify({
            'error': 'Invoice quota exceeded',
            'quota_exceeded': True
        }), 403
    
    try:
        item.status = 'processing'
        item.target_tab = target_tab
        db.session.commit()
        
        # Use existing parser infrastructure
        from app.parsers.parser_service import InvoiceParserService
        from app.web.upload import save_invoice_to_db, check_supplier_account_fraud, register_supplier_account
        
        master_parser = InvoiceParserService()
        
        user_markup_settings = {
            'is_admin': current_user.is_admin,
            'default_markup': current_user.default_markup or 50.0
        }
        
        # Parse the queued file
        parsed_invoices = master_parser.parse(
            item.file_path,
            use_claude=True,
            document_type=target_tab,
            user_markup_settings=user_markup_settings
        )
        
        results = []
        errors = []
        supplier_account_checked = False
        
        for invoice_data in parsed_invoices:
            if invoice_data.get('success'):
                if not current_user.can_upload_invoice:
                    errors.append('Quota exceeded')
                    break
                
                supplier_name = invoice_data.get('supplier', 'Unknown')
                supplier_account_number = invoice_data.get('supplier_account_number')
                
                # Fraud check
                if not supplier_account_checked and supplier_account_number:
                    fraud_check = check_supplier_account_fraud(
                        supplier_name, supplier_account_number, current_user.id
                    )
                    supplier_account_checked = True
                    
                    if not fraud_check['allowed']:
                        item.status = 'queued'  # Put it back
                        db.session.commit()
                        return jsonify({
                            'error': fraud_check['message'],
                            'fraud_detected': True
                        }), 403
                
                # Save to database
                saved_invoice = save_invoice_to_db(
                    invoice_data, item.original_filename, current_user.id, target_tab
                )
                
                if supplier_account_number:
                    register_supplier_account(supplier_name, supplier_account_number, current_user.id)
                
                current_user.use_invoice_quota(1)
                db.session.commit()
                
                items = invoice_data.get('items', [])
                total = sum(i.get('total_amount', 0) for i in items)
                
                results.append({
                    'id': saved_invoice.id,
                    'supplier': supplier_name,
                    'items_count': len(items),
                    'total': total,
                    'success': True
                })
            else:
                errors.append(invoice_data.get('error', 'Unknown error'))
        
        if results:
            item.status = 'completed'
            item.processed_at = datetime.utcnow()
            item.processed_invoice_id = results[0]['id']
            item.supplier_name = results[0].get('supplier')
            db.session.commit()
            
            return jsonify({
                'success': True,
                'processed': len(results),
                'results': results,
                'errors': errors,
                'target_tab': target_tab,
                'remaining': current_user.invoices_remaining if current_user.invoices_remaining != float('inf') else 'unlimited'
            })
        else:
            item.status = 'failed'
            db.session.commit()
            return jsonify({'error': errors[0] if errors else 'Processing failed'}), 400
    
    except Exception as e:
        current_app.logger.error(f"Error processing queue item {queue_id}: {str(e)}", exc_info=True)
        item.status = 'queued'  # Put it back on failure
        db.session.commit()
        return jsonify({'error': f'Processing error: {str(e)}'}), 500


@bp.route('/api/<int:queue_id>/delete', methods=['DELETE'])
@login_required
def api_delete_from_queue(queue_id):
    """Remove an item from the queue"""
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    item = QueuedInvoice.query.filter_by(id=queue_id, user_id=current_user.id).first()
    
    if not item:
        return jsonify({'error': 'Not found'}), 404
    
    # Delete the file
    try:
        if os.path.exists(item.file_path):
            os.remove(item.file_path)
    except Exception as e:
        current_app.logger.warning(f"Could not delete file {item.file_path}: {e}")
    
    db.session.delete(item)
    db.session.commit()
    
    return jsonify({'success': True})


@bp.route('/api/batch-process', methods=['POST'])
@login_required
def api_batch_process():
    """Process multiple queued items at once"""
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    data = request.json
    queue_ids = data.get('ids', [])
    target_tab = data.get('target_tab', 'invoice')
    
    if not queue_ids:
        return jsonify({'error': 'No items selected'}), 400
    
    results = []
    errors = []
    
    for qid in queue_ids:
        item = QueuedInvoice.query.filter_by(id=qid, user_id=current_user.id, status='queued').first()
        if not item:
            errors.append(f'Item {qid} not found or already processed')
            continue
        
        # Process each item via the single process endpoint logic
        try:
            # Make an internal call to process
            with current_app.test_request_context(
                json={'target_tab': target_tab}
            ):
                # Reuse the process logic
                response = api_process_from_queue(qid)
                if hasattr(response, 'json'):
                    resp_data = response.json
                else:
                    resp_data = response[0].json if isinstance(response, tuple) else response.get_json()
                
                if resp_data.get('success'):
                    results.append({'id': qid, 'success': True})
                else:
                    errors.append(f'Item {qid}: {resp_data.get("error", "Failed")}')
        except Exception as e:
            errors.append(f'Item {qid}: {str(e)}')
    
    return jsonify({
        'success': len(results) > 0,
        'processed': len(results),
        'results': results,
        'errors': errors
    })


@bp.route('/api/clear-completed', methods=['POST'])
@login_required
def api_clear_completed():
    """Remove all completed/failed items from queue"""
    from app.models.queued_invoice import QueuedInvoice
    from app.extensions import db
    
    items = QueuedInvoice.query.filter(
        QueuedInvoice.user_id == current_user.id,
        QueuedInvoice.status.in_(['completed', 'failed'])
    ).all()
    
    count = len(items)
    
    for item in items:
        try:
            if os.path.exists(item.file_path):
                os.remove(item.file_path)
        except Exception:
            pass
        db.session.delete(item)
    
    db.session.commit()
    
    return jsonify({'success': True, 'cleared': count})
