"""User model"""
from app.extensions import db
from flask_login import UserMixin
from datetime import datetime, timedelta
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
    
    # Subscription fields
    subscription_plan = db.Column(db.String(20), default='trial')  # trial, basic, pro, cancelled
    subscription_status = db.Column(db.String(20), default='active')  # active, past_due, cancelled
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    trial_ends_at = db.Column(db.DateTime)
    subscription_ends_at = db.Column(db.DateTime)

    # Setup wizard & onboarding
    setup_completed = db.Column(db.Boolean, default=False)
    tour_completed = db.Column(db.Boolean, default=False)
    company_name = db.Column(db.String(255))
    default_markup = db.Column(db.Float, default=50.0)
    
    # Email notifications
    trial_reminder_sent = db.Column(db.Boolean, default=False)
    
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
    
    def start_trial(self):
        """Start 7-day free trial"""
        self.subscription_plan = 'trial'
        self.subscription_status = 'active'
        self.trial_ends_at = datetime.utcnow() + timedelta(days=7)
    
    @property
    def is_trial_active(self):
        """Check if trial is still active"""
        if self.subscription_plan != 'trial':
            return False
        if not self.trial_ends_at:
            return False
        return datetime.utcnow() < self.trial_ends_at
    
    @property
    def trial_days_remaining(self):
        """Get days remaining in trial"""
        if not self.trial_ends_at:
            return 0
        remaining = (self.trial_ends_at - datetime.utcnow()).days
        return max(0, remaining)
    
    @property
    def has_active_subscription(self):
        """Check if user has active paid subscription or valid trial"""
        # Admin always has access
        if self.is_admin:
            return True
        # Check paid subscription
        if self.subscription_plan in ['basic', 'pro'] and self.subscription_status == 'active':
            return True
        # Check trial
        if self.is_trial_active:
            return True
        return False
    
    @property
    def can_sync_to_accounting(self):
        """Check if user can sync to QuickBooks/Xero"""
        return self.has_active_subscription
    
    @property
    def monthly_invoice_limit(self):
        """Get monthly invoice limit based on plan"""
        if self.is_admin:
            return float('inf')  # Unlimited for admin
        limits = {
            'trial': 10,
            'basic': 100,
            'pro': float('inf'),  # Unlimited
            'cancelled': 0
        }
        return limits.get(self.subscription_plan, 0)
    
    def get_invoices_this_month(self):
        """Get count of invoices uploaded this month"""
        from app.models.invoice import Invoice
        from sqlalchemy import func
        
        first_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count = Invoice.query.filter(
            Invoice.user_id == self.id,
            Invoice.created_at >= first_of_month
        ).count()
        return count
    
    @property
    def invoices_remaining(self):
        """Get remaining invoices for this month"""
        limit = self.monthly_invoice_limit
        if limit == float('inf'):
            return float('inf')
        used = self.get_invoices_this_month()
        return max(0, limit - used)
    
    @property
    def can_upload_invoice(self):
        """Check if user can upload more invoices"""
        if self.is_admin:
            return True
        if not self.has_active_subscription:
            return False
        return self.invoices_remaining > 0
    
    @property 
    def plan_display_name(self):
        """Get friendly plan name"""
        names = {
            'trial': 'Free Trial',
            'basic': 'Basic',
            'pro': 'Pro',
            'cancelled': 'Cancelled'
        }
        return names.get(self.subscription_plan, 'Unknown')
    
    def __repr__(self):
        return f'<User {self.email}>'
