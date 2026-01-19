"""Xero Connection Model"""
from datetime import datetime
from app.extensions import db


class XeroConnection(db.Model):
    """Stores Xero OAuth tokens and settings for each user"""
    __tablename__ = 'xero_connections'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    
    # Xero tenant (organisation) info
    tenant_id = db.Column(db.String(100), nullable=False)  # Xero organisation ID
    tenant_name = db.Column(db.String(255))  # Organisation name
    
    # OAuth tokens
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    token_expires_at = db.Column(db.DateTime, nullable=False)
    
    # Connection status
    is_active = db.Column(db.Boolean, default=True)
    connected_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_sync_at = db.Column(db.DateTime)
    
    # Default account settings
    default_expense_account_code = db.Column(db.String(50))
    default_expense_account_name = db.Column(db.String(255))
    default_sales_account_code = db.Column(db.String(50))
    default_sales_account_name = db.Column(db.String(255))
    
    # Sync preferences
    auto_sync = db.Column(db.Boolean, default=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('xero_connection', uselist=False))
    
    def __repr__(self):
        return f'<XeroConnection {self.tenant_name} for user {self.user_id}>'
    
    @property
    def is_token_expired(self):
        """Check if the access token has expired"""
        return datetime.utcnow() >= self.token_expires_at
