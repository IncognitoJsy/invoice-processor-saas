"""Authentication routes"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models.user import User
from datetime import datetime
import re
import requests as http_requests

bp = Blueprint('auth', __name__)


def validate_password(password):
    """
    Validate password meets Intuit Developer Services password policy.
    
    Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - Not a commonly used password
    
    Returns (is_valid: bool, error_message: str or None)
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?`~]', password):
        return False, 'Password must contain at least one special character (!@#$%^&* etc.).'
    
    # Check against common passwords
    common_passwords = {
        'password', 'password1', '12345678', 'qwerty123', 'letmein1',
        'welcome1', 'monkey123', 'dragon12', 'master12', 'abc12345',
        'Password1', 'Password1!', 'Qwerty123!', 'Admin123!',
    }
    if password.lower().rstrip('!@#$%^&*') in {p.lower() for p in common_passwords}:
        return False, 'That password is too common. Please choose a stronger password.'
    
    return True, None


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
        # 1.0 = very likely human, 0.0 = very likely bot
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
    """Login page"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
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
            
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            login_user(user, remember=remember)
            
            # Check if user needs to complete setup
            if not user.setup_completed:
                return redirect(url_for('setup.index'))
            
            return redirect(url_for('dashboard.index'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registration page"""
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
@login_required
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out', 'info')
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
