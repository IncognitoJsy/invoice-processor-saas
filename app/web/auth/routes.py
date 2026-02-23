"""Authentication routes"""
from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, current_user
from datetime import datetime
from app.web.auth import bp
from app.utils.password_validation import validate_password
from app.models.user import User
from app.extensions import db
import requests as http_requests
import time
from collections import defaultdict

# Login rate limiting - 5 attempts per 15 minutes per IP
_login_attempts = defaultdict(list)

def check_login_rate_limit():
    ip = request.remote_addr or "unknown"
    now = time.time()
    window = 900  # 15 minutes
    max_attempts = 5
    
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < window]
    
    if len(_login_attempts[ip]) >= max_attempts:
        return False
    return True

def record_login_attempt():
    ip = request.remote_addr or "unknown"
    _login_attempts[ip].append(time.time())


def verify_recaptcha(token, expected_action=None):
    """
    Verify reCAPTCHA v3 token with Google.
    
    Returns (success: bool, score: float or None)
    - success=True if token is valid and score >= 0.5
    - If RECAPTCHA_SECRET_KEY is not configured, always returns True (graceful degradation)
    """
    secret_key = current_app.config.get('RECAPTCHA_SECRET_KEY')
    
    # If reCAPTCHA is not configured, skip verification (allows dev/staging without keys)
    if not secret_key:
        return True, None
    
    if not token:
        current_app.logger.warning('reCAPTCHA token missing from form submission')
        return False, 0.0
    
    try:
        response = http_requests.post(
            'https://www.google.com/recaptcha/api/siteverify',
            data={
                'secret': secret_key,
                'response': token,
                'remoteip': request.remote_addr
            },
            timeout=5
        )
        result = response.json()
        
        success = result.get('success', False)
        score = result.get('score', 0.0)
        action = result.get('action', '')
        
        current_app.logger.info(
            f"reCAPTCHA verification: success={success}, score={score}, action={action}"
        )
        
        # Verify action matches expected action (prevents token reuse across forms)
        if expected_action and action != expected_action:
            current_app.logger.warning(
                f"reCAPTCHA action mismatch: expected={expected_action}, got={action}"
            )
            return False, score
        
        # Score threshold: 0.5 is Google's recommended threshold
        if success and score >= 0.5:
            return True, score
        else:
            current_app.logger.warning(f"reCAPTCHA failed: success={success}, score={score}")
            return False, score
            
    except Exception as e:
        current_app.logger.error(f"reCAPTCHA verification error: {str(e)}")
        # On network error, allow the request (don't block users due to Google outage)
        return True, None


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        # Rate limit check
        if not check_login_rate_limit():
            flash('Too many login attempts. Please try again in 15 minutes.', 'error')
            return render_template('auth/login.html')
        
        # Verify reCAPTCHA
        recaptcha_token = request.form.get('recaptcha_token')
        recaptcha_ok, recaptcha_score = verify_recaptcha(recaptcha_token, expected_action='login')
        if not recaptcha_ok:
            flash('Security verification failed. Please try again.', 'error')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated. Please contact support.', 'error')
                return render_template('auth/login.html')
            
            # Check if MFA is enabled
            if user.mfa_enabled:
                # Store user ID in session for MFA verification step
                session['mfa_user_id'] = user.id
                session['mfa_remember'] = bool(remember)
                return redirect(url_for('auth.mfa_verify'))
            
            # No MFA - log in directly
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            
            # Check if user needs to complete setup
            if not user.setup_completed:
                return redirect(url_for('setup.index'))
            
            return redirect(url_for('dashboard.index'))
        else:
            record_login_attempt()
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')


@bp.route('/mfa-verify', methods=['GET', 'POST'])
def mfa_verify():
    """MFA verification page - shown after successful password entry"""
    user_id = session.get('mfa_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    user = User.query.get(user_id)
    if not user or not user.mfa_enabled:
        session.pop('mfa_user_id', None)
        session.pop('mfa_remember', None)
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        code = request.form.get('mfa_code', '').strip()
        
        if not code:
            flash('Please enter your authentication code.', 'error')
            return render_template('auth/mfa_verify.html')
        
        # Try TOTP code first
        if user.verify_mfa_code(code):
            # MFA verified - complete login
            remember = session.pop('mfa_remember', False)
            session.pop('mfa_user_id', None)
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            
            if not user.setup_completed:
                return redirect(url_for('setup.index'))
            
            return redirect(url_for('dashboard.index'))
        
        # Try recovery code
        if user.use_recovery_code(code):
            remember = session.pop('mfa_remember', False)
            session.pop('mfa_user_id', None)
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            
            flash('Recovery code used. You have limited recovery codes remaining.', 'info')
            
            if not user.setup_completed:
                return redirect(url_for('setup.index'))
            
            return redirect(url_for('dashboard.index'))
        
        flash('Invalid code. Please try again or use a recovery code.', 'error')
    
    return render_template('auth/mfa_verify.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        
        # Verify reCAPTCHA
        recaptcha_token = request.form.get('recaptcha_token')
        recaptcha_ok, recaptcha_score = verify_recaptcha(recaptcha_token, expected_action='register')
        if not recaptcha_ok:
            flash('Security verification failed. Please try again.', 'error')
            return render_template('auth/register.html')
        
        if not email or not password:
            flash('Email and password are required', 'error')
            return render_template('auth/register.html')
        
        if password != password_confirm:
            flash('Passwords do not match', 'error')
            return render_template('auth/register.html')
        
        # Validate password strength (Intuit password policy compliance)
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('auth/register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('auth/register.html')
        
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name
        )
        user.set_password(password)
        user.start_trial()
        
        db.session.add(user)
        db.session.commit()
        
        # Log them in directly
        login_user(user)
        
        flash('Welcome to GoZappify! Let\'s get you set up.', 'success')
        return redirect(url_for('setup.index'))
    
    return render_template('auth/register.html')


@bp.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.login'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password - request reset link"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        # Verify reCAPTCHA
        recaptcha_token = request.form.get('recaptcha_token')
        recaptcha_ok, recaptcha_score = verify_recaptcha(recaptcha_token, expected_action='forgot_password')
        if not recaptcha_ok:
            flash('Security verification failed. Please try again.', 'error')
            return render_template('auth/forgot_password.html')
        
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            try:
                from app.models.password_reset import PasswordResetToken
                from app.services.email_service import get_email_service
                
                # Create reset token
                token = PasswordResetToken.create_token(user)
                
                # Build reset URL
                reset_url = url_for('auth.reset_password', token=token.token, _external=True)
                
                # Send email
                email_service = get_email_service()
                result = email_service.send_password_reset(user, reset_url)
                
                if result.get('success'):
                    current_app.logger.info(f"Password reset email sent to {email}")
                else:
                    current_app.logger.error(f"Failed to send reset email: {result.get('error')}")
                    
            except Exception as e:
                current_app.logger.error(f"Password reset error: {str(e)}")
        
        # Always show same message (security - don't reveal if email exists)
        flash('If that email is registered, you will receive a password reset link shortly.', 'info')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password with token"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    from app.models.password_reset import PasswordResetToken
    
    # Validate token
    reset_token = PasswordResetToken.get_valid_token(token)
    
    if not reset_token:
        flash('This password reset link is invalid or has expired.', 'error')
        return redirect(url_for('auth.forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        
        if not password or len(password) < 8:
            flash('Password must be at least 8 characters', 'error')
            return render_template('auth/reset_password.html', token=token)
        
        if password != password_confirm:
            flash('Passwords do not match', 'error')
            return render_template('auth/reset_password.html', token=token)
        
        # Validate password strength (same rules as registration)
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('auth/reset_password.html', token=token)
        
        # Update password
        user = reset_token.user
        user.set_password(password)
        reset_token.mark_used()
        db.session.commit()
        
        # Send confirmation email
        try:
            from app.services.email_service import get_email_service
            email_service = get_email_service()
            email_service.send_password_changed(user)
        except Exception as e:
            current_app.logger.error(f"Failed to send password changed email: {str(e)}")
        
        flash('Your password has been reset. Please log in with your new password.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/reset_password.html', token=token)
