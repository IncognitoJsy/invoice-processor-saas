"""Flask application factory"""
import logging
from flask import Flask, redirect, url_for, render_template
from app.config import config
from app.extensions import db, migrate, login_manager, limiter


def create_app(config_name='default'):
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)
    
    # Create tables if they don't exist (for SQLite on Railway)
    with app.app_context():
        db.create_all()
    
    # Configure logging
    configure_logging(app)
    
    # Register blueprints
    register_blueprints(app)
    
    # Register error handlers
    register_error_handlers(app)
    
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
