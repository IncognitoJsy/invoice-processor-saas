"""Settings routes - Account and preference management"""
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, session
from flask_login import login_required, current_user
from app.extensions import db
from app.utils.password_validation import validate_password
import io
import base64

bp = Blueprint('settings', __name__, url_prefix='/settings')


@bp.route('/')
@login_required
def index():
    """Settings page"""
    return render_template('settings/index.html')


@bp.route('/update-profile', methods=['POST'])
@login_required
def update_profile():
    """Update user profile"""
    data = request.get_json() or request.form
    
    # Update allowed fields
    if 'company_name' in data:
        current_user.company_name = data['company_name']
    
    if 'first_name' in data:
        current_user.first_name = data['first_name']
    
    if 'last_name' in data:
        current_user.last_name = data['last_name']
    
    if 'default_markup' in data:
        try:
            markup = float(data['default_markup'])
            if 0 <= markup <= 200:
                current_user.default_markup = markup
        except (ValueError, TypeError):
            pass
    
    db.session.commit()
    
    if request.is_json:
        return jsonify({'success': True, 'message': 'Profile updated'})
    
    flash('Profile updated successfully', 'success')
    return redirect(url_for('settings.index'))


@bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Change user password"""
    data = request.get_json() or request.form
    
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    confirm_password = data.get('confirm_password')
    
    # Validate
    if not current_password or not new_password:
        if request.is_json:
            return jsonify({'success': False, 'error': 'All fields required'}), 400
        flash('All fields are required', 'error')
        return redirect(url_for('settings.index'))
    
    if not current_user.check_password(current_password):
        if request.is_json:
            return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400
        flash('Current password is incorrect', 'error')
        return redirect(url_for('settings.index'))
    
    if new_password != confirm_password:
        if request.is_json:
            return jsonify({'success': False, 'error': 'New passwords do not match'}), 400
        flash('New passwords do not match', 'error')
        return redirect(url_for('settings.index'))
    
    if len(new_password) < 8:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Password must be at least 8 characters'}), 400
        flash('Password must be at least 8 characters', 'error')
        return redirect(url_for('settings.index'))
    
    # Validate password strength
    is_valid, error_msg = validate_password(new_password)
    if not is_valid:
        if request.is_json:
            return jsonify({'success': False, 'error': error_msg}), 400
        flash(error_msg, 'error')
        return redirect(url_for('settings.index'))
    
    # Update password
    current_user.set_password(new_password)
    db.session.commit()
    
    if request.is_json:
        return jsonify({'success': True, 'message': 'Password changed successfully'})
    
    flash('Password changed successfully', 'success')
    return redirect(url_for('settings.index'))


# ─── MFA Routes ──────────────────────────────────────────────────────────────

@bp.route('/mfa/setup', methods=['POST'])
@login_required
def mfa_setup():
    """Start MFA setup - generate secret and QR code"""
    if current_user.mfa_enabled:
        flash('MFA is already enabled.', 'info')
        return redirect(url_for('settings.index'))
    
    # Generate new secret
    secret = current_user.generate_mfa_secret()
    db.session.commit()
    
    # Generate QR code as base64 image
    try:
        import pyotp
        import qrcode
        
        uri = current_user.get_mfa_uri()
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
    except Exception as e:
        flash(f'Error generating QR code: {str(e)}', 'error')
        return redirect(url_for('settings.index'))
    
    return render_template('settings/mfa_setup.html', 
                         qr_code=qr_base64, 
                         secret=secret)


@bp.route('/mfa/confirm', methods=['POST'])
@login_required
def mfa_confirm():
    """Confirm MFA setup by verifying a code from the authenticator app"""
    code = request.form.get('mfa_code', '').strip()
    
    if not code:
        flash('Please enter the 6-digit code from your authenticator app.', 'error')
        return redirect(url_for('settings.mfa_setup'))
    
    if not current_user.mfa_secret:
        flash('MFA setup not started. Please try again.', 'error')
        return redirect(url_for('settings.index'))
    
    if current_user.verify_mfa_code(code):
        # MFA verified - enable it and generate recovery codes
        current_user.mfa_enabled = True
        recovery_codes = current_user.generate_recovery_codes()
        db.session.commit()
        
        return render_template('settings/mfa_recovery_codes.html', 
                             recovery_codes=recovery_codes)
    else:
        flash('Invalid code. Please check your authenticator app and try again.', 'error')
        # Re-show setup page with QR
        try:
            import qrcode
            uri = current_user.get_mfa_uri()
            qr = qrcode.QRCode(version=1, box_size=6, border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            qr_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return render_template('settings/mfa_setup.html',
                                 qr_code=qr_base64,
                                 secret=current_user.mfa_secret)
        except Exception:
            return redirect(url_for('settings.index'))


@bp.route('/mfa/disable', methods=['POST'])
@login_required
def mfa_disable():
    """Disable MFA - requires password confirmation"""
    password = request.form.get('password', '')
    
    if not current_user.check_password(password):
        flash('Incorrect password. MFA was not disabled.', 'error')
        return redirect(url_for('settings.index'))
    
    current_user.disable_mfa()
    db.session.commit()
    
    flash('Two-factor authentication has been disabled.', 'success')
    return redirect(url_for('settings.index'))


@bp.route('/api/profile')
@login_required
def get_profile():
    """Get current user profile"""
    return jsonify({
        'email': current_user.email,
        'first_name': current_user.first_name,
        'last_name': current_user.last_name,
        'company_name': current_user.company_name,
        'default_markup': current_user.default_markup or 50.0,
        'plan': current_user.subscription_plan,
        'plan_display': current_user.plan_display_name
    })


@bp.route('/update-invoice-style', methods=['POST'])
@login_required
def update_invoice_style():
    """Update invoice template and colour"""
    current_user.invoice_colour = request.form.get('invoice_colour', '#2563eb')
    current_user.invoice_template = request.form.get('invoice_template', 'classic')
    db.session.commit()
    flash('Invoice style updated.', 'success')
    return redirect(url_for('settings.index'))


@bp.route('/upload-logo', methods=['POST'])
@login_required
def upload_logo():
    """Upload company logo - stored as base64 data URL in database"""
    import base64
    from PIL import Image
    import io

    if 'logo' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('settings.index') + '#invoice-style')

    file = request.files['logo']
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('settings.index') + '#invoice-style')

    # Validate file type
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        flash('Please upload a PNG, JPG, GIF, WebP or SVG file.', 'error')
        return redirect(url_for('settings.index') + '#invoice-style')

    try:
        file_data = file.read()

        # For non-SVG images, resize to max 400px wide using Pillow
        if ext != 'svg':
            img = Image.open(io.BytesIO(file_data))
            # Convert RGBA to RGB for JPEG
            if img.mode in ('RGBA', 'P') and ext in ('jpg', 'jpeg'):
                img = img.convert('RGB')
            # Resize if too large
            max_width = 400
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
            # Save back to bytes
            buf = io.BytesIO()
            fmt = 'PNG' if ext == 'png' else 'JPEG' if ext in ('jpg', 'jpeg') else ext.upper()
            img.save(buf, format=fmt, optimize=True)
            file_data = buf.getvalue()

        # Encode as base64 data URL
        mime_types = {
            'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml'
        }
        mime = mime_types.get(ext, 'image/png')
        b64 = base64.b64encode(file_data).decode('utf-8')
        data_url = f'data:{mime};base64,{b64}'

        # Check size — max 500KB encoded
        if len(data_url) > 700000:
            flash('Logo file is too large. Please use an image under 200KB.', 'error')
            return redirect(url_for('settings.index') + '#invoice-style')

        current_user.logo_url = data_url
        db.session.commit()
        flash('Logo uploaded successfully.', 'success')

    except Exception as e:
        flash(f'Error processing image: {str(e)}', 'error')

    return redirect(url_for('settings.index') + '#invoice-style')


@bp.route('/remove-logo', methods=['POST'])
@login_required
def remove_logo():
    """Remove company logo"""
    current_user.logo_url = None
    db.session.commit()
    flash('Logo removed.', 'success')
    return redirect(url_for('settings.index') + '#invoice-style')


@bp.route('/update-bank-details', methods=['POST'])
@login_required
def update_bank_details():
    """Update bank and payment details"""
    current_user.bank_name = request.form.get('bank_name', '').strip() or None
    current_user.bank_account_name = request.form.get('bank_account_name', '').strip() or None
    current_user.bank_account_number = request.form.get('bank_account_number', '').strip() or None
    current_user.bank_sort_code = request.form.get('bank_sort_code', '').strip() or None
    current_user.bank_iban = request.form.get('bank_iban', '').strip() or None
    current_user.default_payment_terms = request.form.get('default_payment_terms', '30')
    current_user.default_invoice_mode = request.form.get('default_invoice_mode', 'itemised')
    current_user.invoice_notes = request.form.get('invoice_notes', '').strip() or None
    db.session.commit()
    flash('Payment details updated successfully.', 'success')
    return redirect(url_for('settings.index'))
