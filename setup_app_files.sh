#!/bin/bash

set -e

echo "🐍 Creating core Python application files..."
echo ""

# ============================================
# WSGI Entry Point
# ============================================
echo "📝 Creating wsgi.py..."
cat > wsgi.py << 'EOF'
"""WSGI entry point for production"""
import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV') or 'production')

if __name__ == "__main__":
    app.run()
EOF

echo "✅ wsgi.py created"

# ============================================
# Management CLI
# ============================================
echo "📝 Creating manage.py..."
cat > manage.py << 'EOF'
"""Management commands for the application"""
import click
from flask.cli import FlaskGroup
from app import create_app, db

def create_cli_app():
    return create_app()

cli = FlaskGroup(create_app=create_cli_app)

@cli.command()
def init_db():
    """Initialize the database"""
    db.create_all()
    click.echo('Database initialized!')

@cli.command()
def seed_db():
    """Seed the database with sample data"""
    click.echo('Seeding database...')
    # Add your seed logic here
    click.echo('Database seeded!')

if __name__ == '__main__':
    cli()
EOF

echo "✅ manage.py created"

# ============================================
# Flask Application Factory
# ============================================
echo "📝 Creating app/__init__.py..."
cat > app/__init__.py << 'EOF'
"""Flask application factory"""
import logging
from flask import Flask
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
        return {'message': 'Invoice Processor API', 'status': 'running'}, 200
    
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
    from app.web import dashboard, invoices, queue, settings
    
    # Web interface
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(invoices.bp)
    app.register_blueprint(queue.bp)
    app.register_blueprint(settings.bp)

def register_error_handlers(app):
    """Register error handlers"""
    @app.errorhandler(404)
    def not_found_error(error):
        return {'error': 'Not found'}, 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return {'error': 'Internal server error'}, 500
EOF

echo "✅ app/__init__.py created"

# ============================================
# Configuration
# ============================================
echo "📝 Creating app/config.py..."
cat > app/config.py << 'EOF'
"""Application configuration"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Redis
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # QuickBooks
    QUICKBOOKS_CLIENT_ID = os.environ.get('QUICKBOOKS_CLIENT_ID')
    QUICKBOOKS_CLIENT_SECRET = os.environ.get('QUICKBOOKS_CLIENT_SECRET')
    QUICKBOOKS_REDIRECT_URI = os.environ.get('QUICKBOOKS_REDIRECT_URI')
    QUICKBOOKS_ENVIRONMENT = os.environ.get('QUICKBOOKS_ENVIRONMENT', 'production')
    
    # OpenAI
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    
    # Telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
    
    # File Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
    
    # Email monitoring
    GMAIL_CHECK_INTERVAL = int(os.environ.get('GMAIL_CHECK_INTERVAL', 900))
    GMAIL_CREDENTIALS_PATH = os.environ.get('GMAIL_CREDENTIALS_PATH', 'credentials.json')
    
    # Rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
EOF

echo "✅ app/config.py created"

# ============================================
# Extensions
# ============================================
echo "📝 Creating app/extensions.py..."
cat > app/extensions.py << 'EOF'
"""Flask extensions"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configure login manager
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
EOF

echo "✅ app/extensions.py created"

# ============================================
# Web Blueprints (Placeholders)
# ============================================
echo "📝 Creating web blueprints..."

cat > app/web/dashboard.py << 'EOF'
"""Dashboard routes"""
from flask import Blueprint, render_template

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@bp.route('/')
def index():
    return {'message': 'Dashboard'}, 200
EOF

cat > app/web/invoices.py << 'EOF'
"""Invoice routes"""
from flask import Blueprint

bp = Blueprint('invoices', __name__, url_prefix='/invoices')

@bp.route('/')
def index():
    return {'message': 'Invoices'}, 200
EOF

cat > app/web/queue.py << 'EOF'
"""Queue management routes"""
from flask import Blueprint

bp = Blueprint('queue', __name__, url_prefix='/queue')

@bp.route('/')
def index():
    return {'message': 'Queue'}, 200
EOF

cat > app/web/settings.py << 'EOF'
"""Settings routes"""
from flask import Blueprint

bp = Blueprint('settings', __name__, url_prefix='/settings')

@bp.route('/')
def index():
    return {'message': 'Settings'}, 200
EOF

echo "✅ Web blueprints created"

# ============================================
# Database Models
# ============================================
echo "📝 Creating database models..."

cat > app/models/user.py << 'EOF'
"""User model"""
from app.extensions import db
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model, UserMixin):
    """User account model"""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.email}>'
EOF

cat > app/models/invoice.py << 'EOF'
"""Invoice model"""
from app.extensions import db
from datetime import datetime

class Invoice(db.Model):
    """Invoice queue item"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Supplier info
    supplier_name = db.Column(db.String(255), nullable=False, index=True)
    supplier_email = db.Column(db.String(255))
    
    # Invoice details
    invoice_number = db.Column(db.String(255))
    invoice_date = db.Column(db.Date)
    invoice_type = db.Column(db.String(50))  # 'invoice' or 'credit'
    
    # Job reference
    job_reference = db.Column(db.String(255), index=True)
    
    # File details
    pdf_path = db.Column(db.String(500))
    pdf_filename = db.Column(db.String(255))
    
    # Processing status
    status = db.Column(db.String(50), default='pending', index=True)
    # Status: pending, processing, completed, failed, skipped
    
    processed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    
    # Email metadata
    email_subject = db.Column(db.String(500))
    email_date = db.Column(db.DateTime)
    gmail_message_id = db.Column(db.String(255), unique=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Invoice {self.supplier_name} - {self.job_reference}>'
EOF

cat > app/models/product.py << 'EOF'
"""Product model (QuickBooks cache)"""
from app.extensions import db
from datetime import datetime

class Product(db.Model):
    """Cached QuickBooks product"""
    id = db.Column(db.Integer, primary_key=True)
    
    # QuickBooks IDs
    qb_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    qb_sync_token = db.Column(db.String(50))
    
    # Product details
    name = db.Column(db.String(255), nullable=False)
    sku = db.Column(db.String(255), index=True)
    description = db.Column(db.Text)
    
    # Pricing
    unit_price = db.Column(db.Numeric(10, 2))
    purchase_cost = db.Column(db.Numeric(10, 2))
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Product {self.sku} - {self.name}>'
EOF

# Update models __init__.py
cat > app/models/__init__.py << 'EOF'
"""Database models"""
from app.models.user import User
from app.models.invoice import Invoice
from app.models.product import Product

__all__ = ['User', 'Invoice', 'Product']
EOF

echo "✅ Database models created"

# ============================================
# Complete!
# ============================================
echo ""
echo "🎉 Core application files created!"
echo ""
echo "✅ wsgi.py (entry point)"
echo "✅ manage.py (CLI commands)"
echo "✅ app/__init__.py (Flask factory)"
echo "✅ app/config.py (configuration)"
echo "✅ app/extensions.py (Flask extensions)"
echo "✅ app/models/ (database models)"
echo "✅ app/web/ (route blueprints)"
echo ""
echo "📋 Next: Create services and utilities"
echo ""
