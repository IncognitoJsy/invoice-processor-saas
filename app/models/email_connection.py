"""Email Connection model - stores OAuth tokens for email monitoring"""
from app.extensions import db
from datetime import datetime
from cryptography.fernet import Fernet
import os
import json


class EmailConnection(db.Model):
    """User's connected email account for auto-fetching invoices"""
    __tablename__ = 'email_connection'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Provider info
    provider = db.Column(db.String(20), nullable=False)  # 'gmail' or 'outlook'
    email_address = db.Column(db.String(255), nullable=False)
    
    # Encrypted OAuth token
    encrypted_token = db.Column(db.Text)
    
    # Settings
    is_active = db.Column(db.Boolean, default=True)  # toggle monitoring on/off
    poll_interval_minutes = db.Column(db.Integer, default=15)
    
    # Tracking
    last_checked = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    emails_fetched_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('email_connections', lazy='dynamic'))
    
    @staticmethod
    def _get_encryption_key():
        """Get or generate encryption key from environment"""
        key = os.environ.get('EMAIL_TOKEN_ENCRYPTION_KEY')
        if not key:
            # In production, this MUST be set as an environment variable
            # For development, generate a consistent key
            key = Fernet.generate_key().decode()
            os.environ['EMAIL_TOKEN_ENCRYPTION_KEY'] = key
        return key.encode() if isinstance(key, str) else key
    
    def set_token(self, token_data):
        """Encrypt and store OAuth token"""
        f = Fernet(self._get_encryption_key())
        token_json = json.dumps(token_data)
        self.encrypted_token = f.encrypt(token_json.encode()).decode()
    
    def get_token(self):
        """Decrypt and return OAuth token"""
        if not self.encrypted_token:
            return None
        f = Fernet(self._get_encryption_key())
        token_json = f.decrypt(self.encrypted_token.encode()).decode()
        return json.loads(token_json)
    
    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'email_address': self.email_address,
            'is_active': self.is_active,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'emails_fetched_count': self.emails_fetched_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    def __repr__(self):
        return f'<EmailConnection {self.id}: {self.email_address} ({self.provider})>'


class SupplierFilter(db.Model):
    """Supplier email addresses to monitor for a user"""
    __tablename__ = 'supplier_filter'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Supplier info
    supplier_name = db.Column(db.String(100), nullable=False)
    email_address = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('supplier_filters', lazy='dynamic'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'supplier_name': self.supplier_name,
            'email_address': self.email_address,
            'is_active': self.is_active
        }
    
    def __repr__(self):
        return f'<SupplierFilter {self.id}: {self.supplier_name} ({self.email_address})>'
