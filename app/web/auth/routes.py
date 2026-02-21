"""Authentication routes"""
from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, current_user
from datetime import datetime
from app.web.auth import bp
from app.utils.password_validation import validate_password
from app.models.user import User
from app.extensions import db
import re


def sanitize_input(value, max_length=255, allow_email=False):
    """
    Sanitize user input to prevent SQL injection and XSS.
    
    SQLAlchemy ORM already uses parameterised queries, but this adds
    defence-in-depth for Intuit's security review (Synopsys pen test).
    """
    if not value or not isinstance(value, str):
        return value
    
    # Strip whitespace
    value = value.strip()
    
    # Truncate to max length
    value = value[:max_length]
    
    # Remove null bytes
    value = value.replace('\x00', '')
    
    if allow_email:
        # For email: only allow valid email characters
        value = re.sub(r'[^\w.@+\-]', '', value)
    else:
        # For names: allow letters, spaces, hyphens, apostrophes
        # Strip anything that looks like SQL or script injection
        value = re.sub(r'[;<>\'\"\\\/\(\)\{\}\[\]]', '', value)
    
    return value


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = sanitize_input(request.form.get('email'), max_length=255, allow_email=True)
        password = request.form.get('password')  # Don't sanitize password (would break valid passwords)
        remember = request.form.get('remember', False)
        
        if not email:
            flash('Please enter a valid email address', 'error')
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
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    if request.method == 'POST':
        email = sanitize_input(request.form.get('email'), max_length=255, allow_email=True)
        password = request.form.get('password')  # Don't sanitize (would break valid passwords)
        password_confirm = request.form.get('password_confirm')
        first_name = sanitize_input(request.form.get('first_name'), max_length=100)
        last_name = sanitize_input(request.form.get('last_name'), max_length=100)
        
        if not email or not password:
            flash('Email and password are required', 'error')
            return render_template('auth/register.html')
        
        if password != password_confirm:
            flash('Passwords do not match', 'error')
            return render_template('auth/register.html')
        
        if len(password) < 8:
            flash('Password must be at least 8 characters', 'error')
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
