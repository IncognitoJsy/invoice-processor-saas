"""QuickBooks Connection Model"""
from app.extensions import db
from datetime import datetime


class QuickBooksConnection(db.Model):
    """Store QuickBooks OAuth tokens and settings per user"""
    __tablename__ = 'quickbooks_connection'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)
    
    # QuickBooks company info
    realm_id = db.Column(db.String(255), nullable=False)  # Company ID
    company_name = db.Column(db.String(255))
    
    # OAuth tokens
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text, nullable=False)
    token_expires_at = db.Column(db.DateTime)
    
    # Settings
    default_income_account_id = db.Column(db.String(50))
    default_income_account_name = db.Column(db.String(255))
    default_expense_account_id = db.Column(db.String(50))
    default_expense_account_name = db.Column(db.String(255))
    auto_sync = db.Column(db.Boolean, default=False)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    last_sync_at = db.Column(db.DateTime)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('User', backref=db.backref('quickbooks_connection', uselist=False))
    
    def __repr__(self):
        return f'<QuickBooksConnection {self.company_name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'realm_id': self.realm_id,
            'company_name': self.company_name,
            'is_active': self.is_active,
            'auto_sync': self.auto_sync,
            'default_income_account_id': self.default_income_account_id,
            'default_income_account_name': self.default_income_account_name,
            'default_expense_account_id': self.default_expense_account_id,
            'default_expense_account_name': self.default_expense_account_name,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
