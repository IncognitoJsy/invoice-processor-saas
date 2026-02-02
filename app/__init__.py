"""Flask application factory"""
import logging
from flask import Flask, redirect, url_for, render_template
from app.config import config
from app.extensions import db, migrate, login_manager, limiter, csrf


def create_app(config_name='default'):
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)
    
    # Create tables if they don't exist (for SQLite on Railway)
    with app.app_context():
        db.create_all()
    
    # Configure logging
    configure_logging(app)
    
    # Register blueprints
    register_blueprints(app)
    
    # Exempt API and webhook routes from CSRF (they use fetch() with session cookies or are external webhooks)
    from app.web import upload, user_api, integrations, tasks, part_number_routes, billing
    csrf.exempt(upload.bp)
    csrf.exempt(user_api.bp)
    csrf.exempt(integrations.bp)
    csrf.exempt(tasks.bp)
    csrf.exempt(part_number_routes.part_number_bp)
    csrf.exempt(billing.bp)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Security headers
    register_security_headers(app)
    
    # Health check endpoint
    @app.route('/health')
    def health():
        return {'status': 'healthy'}, 200
    
    @app.route('/')
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for('dashboard.index'))
        return render_template('landing/index.html')
    
    @app.route('/robots.txt')
    def robots():
        return app.send_static_file('robots.txt')
    
    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('images/favicon.ico')
    
    return app


def configure_logging(app):
    """Configure application logging"""
    if not app.debug:
        import os
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        file_handler = logging.FileHandler('logs/app.log')
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Invoice Processor startup')


def register_blueprints(app):
    """Register Flask blueprints"""
    from app.web import dashboard, invoices, queue, settings, upload, auth, integrations, billing, setup, part_number_routes
    from app.web import quotes
    from app.web import user_api
    from app.web import tasks
    from app.web import pages
    
    # Auth (must be first!)
    app.register_blueprint(auth.bp)
    app.register_blueprint(billing.bp)
    
    # Web interface
    app.register_blueprint(integrations.bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(invoices.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(queue.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(user_api.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(part_number_routes.part_number_bp)
    
    # Scheduled tasks (called by external cron)
    app.register_blueprint(tasks.bp)


def register_security_headers(app):
    """Add security headers to all responses"""
    
    @app.after_request
    def add_security_headers(response):
        # Prevent clickjacking - block all framing
        response.headers['X-Frame-Options'] = 'DENY'
        
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # XSS protection (legacy browsers)
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy - send origin only to same-origin, nothing to cross-origin
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy - disable unused browser features
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
        
        # HSTS - enforce HTTPS (1 year, include subdomains)
        # Only set on HTTPS responses to avoid issues in local dev
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        # Content Security Policy
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://js.stripe.com https://appcenter.intuit.com",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com",
            "img-src 'self' data: https:",
            "connect-src 'self' https://appcenter.intuit.com https://oauth.platform.intuit.com https://sandbox-quickbooks.api.intuit.com https://quickbooks.api.intuit.com https://api.stripe.com",
            "frame-src https://js.stripe.com https://appcenter.intuit.com",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self' https://appcenter.intuit.com",
        ]
        response.headers['Content-Security-Policy'] = '; '.join(csp_directives)
        
        return response


def register_error_handlers(app):
    """Register error handlers with nice templates"""
    from flask import request
    
    @app.errorhandler(404)
    def not_found_error(error):
        # Return JSON for API requests, HTML for browser requests
        if request.path.startswith('/api/') or request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return {'error': 'Not found'}, 404
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(403)
    def forbidden_error(error):
        if request.path.startswith('/api/') or request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return {'error': 'Forbidden'}, 403
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith('/api/') or request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return {'error': 'Internal server error'}, 500
        return render_template('errors/500.html'), 500


@login_manager.user_loader
def load_user(user_id):
    """Load user for Flask-Login"""
    from app.models.user import User
    return User.query.get(int(user_id))


login_manager.login_view = 'auth.login'
