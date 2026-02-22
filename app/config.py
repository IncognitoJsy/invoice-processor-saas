"""Application configuration"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session security (base settings - overridden in Production)
    SESSION_COOKIE_HTTPONLY = True      # Prevent JS access to session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'    # CSRF protection
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours
    
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

    # reCAPTCHA v3
    RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY')
    RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY')

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True        # HTTPS only
    SESSION_COOKIE_HTTPONLY = True       # Prevent JS access
    SESSION_COOKIE_SAMESITE = 'Lax'     # CSRF protection
    REMEMBER_COOKIE_SECURE = True       # "Remember me" cookie also HTTPS only
    REMEMBER_COOKIE_HTTPONLY = True      # "Remember me" cookie no JS access
    REMEMBER_COOKIE_SAMESITE = 'Lax'    # "Remember me" CSRF protection

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
