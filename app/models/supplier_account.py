"""Supplier Account model - tracks supplier account numbers for fraud prevention"""
from app.extensions import db
from datetime import datetime


class SupplierAccount(db.Model):
    """
    Tracks supplier account numbers to prevent free trial abuse.
    When a user uploads an invoice, we extract their supplier account number.
    If a new trial user tries to upload with an account number already linked
    to another user, we block them and prompt to upgrade.
    """
    __tablename__ = 'supplier_account'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # The supplier (YESSS, CEF, Wholesale Electrics)
    supplier_name = db.Column(db.String(100), nullable=False, index=True)
    
    # The customer's account number with that supplier
    # e.g., "6729" for Wholesale, "093/47669" for YESSS, "86100012" for CEF
    account_number = db.Column(db.String(100), nullable=False, index=True)
    
    # First user to use this account number
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('supplier_accounts', lazy='dynamic'))
    
    # Timestamps
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Count of invoices processed with this account
    invoice_count = db.Column(db.Integer, default=1)
    
    # Unique constraint: one account number per supplier should only belong to one user
    __table_args__ = (
        db.UniqueConstraint('supplier_name', 'account_number', name='uq_supplier_account'),
    )
    
    def __repr__(self):
        return f'<SupplierAccount {self.supplier_name}: {self.account_number} -> User {self.user_id}>'
    
    @classmethod
    def check_account(cls, supplier_name: str, account_number: str, user_id: int) -> dict:
        """
        Check if a supplier account number can be used by this user.
        
        Returns:
            {
                'allowed': True/False,
                'reason': str or None,
                'existing_user_id': int or None
            }
        """
        if not account_number:
            # No account number found - allow (can't track)
            return {'allowed': True, 'reason': None, 'existing_user_id': None}
        
        # Normalize account number (strip whitespace, uppercase)
        account_number = account_number.strip().upper()
        supplier_name = supplier_name.strip().upper()
        
        # Check if this account exists
        existing = cls.query.filter_by(
            supplier_name=supplier_name,
            account_number=account_number
        ).first()
        
        if not existing:
            # New account - will be registered to this user
            return {'allowed': True, 'reason': 'new_account', 'existing_user_id': None}
        
        if existing.user_id == user_id:
            # Same user - allowed
            return {'allowed': True, 'reason': 'same_user', 'existing_user_id': None}
        
        # Different user owns this account
        return {
            'allowed': False,
            'reason': 'account_exists',
            'existing_user_id': existing.user_id
        }
    
    @classmethod
    def register_account(cls, supplier_name: str, account_number: str, user_id: int) -> 'SupplierAccount':
        """
        Register a supplier account to a user, or update if already exists for same user.
        """
        if not account_number:
            return None
        
        # Normalize
        account_number = account_number.strip().upper()
        supplier_name = supplier_name.strip().upper()
        
        # Check if exists
        existing = cls.query.filter_by(
            supplier_name=supplier_name,
            account_number=account_number
        ).first()
        
        if existing:
            if existing.user_id == user_id:
                # Update count and last seen
                existing.invoice_count += 1
                existing.last_seen_at = datetime.utcnow()
                db.session.commit()
                return existing
            else:
                # Different user - shouldn't happen if check_account was called first
                raise ValueError(f"Account {account_number} already belongs to user {existing.user_id}")
        
        # Create new
        new_account = cls(
            supplier_name=supplier_name,
            account_number=account_number,
            user_id=user_id
        )
        db.session.add(new_account)
        db.session.commit()
        return new_account
    
    @classmethod
    def get_user_accounts(cls, user_id: int) -> list:
        """Get all supplier accounts for a user"""
        return cls.query.filter_by(user_id=user_id).all()
