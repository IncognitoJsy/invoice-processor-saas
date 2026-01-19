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
    subscription_started_at = db.Column(db.DateTime)  # NEW: Track billing period start
    
    # Bonus invoices (purchased top-ups)
    bonus_invoices = db.Column(db.Integer, default=0)  # NEW: Extra invoices purchased

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
    
    def start_paid_subscription(self, plan='basic'):
        """Start a paid subscription - resets quota"""
        self.subscription_plan = plan
        self.subscription_status = 'active'
        self.subscription_started_at = datetime.utcnow()  # Reset billing period
        self.bonus_invoices = 0  # Reset bonus invoices on new subscription
    
    def renew_subscription(self):
        """Called when subscription renews (e.g., from Stripe webhook)"""
        self.subscription_started_at = datetime.utcnow()  # Reset billing period
        # Note: bonus_invoices are NOT reset on renewal - they carry over
    
    def add_bonus_invoices(self, count):
        """Add purchased bonus invoices"""
        self.bonus_invoices = (self.bonus_invoices or 0) + count
    
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
            'trial': 25,  # Updated from 10 to 25
            'basic': 100,
            'pro': float('inf'),  # Unlimited
            'cancelled': 0
        }
        return limits.get(self.subscription_plan, 0)
    
    @property
    def billing_period_start(self):
        """Get the start of the current billing period"""
        if self.subscription_plan == 'trial':
            # For trial, use account creation date
            return self.created_at
        
        if self.subscription_started_at:
            # Calculate current billing period based on subscription start
            now = datetime.utcnow()
            start = self.subscription_started_at
            
            # Find the most recent billing period start
            # (subscription_started_at + N months where result <= now)
            months_elapsed = 0
            while True:
                next_period = start + timedelta(days=30 * (months_elapsed + 1))
                if next_period > now:
                    break
                months_elapsed += 1
            
            return start + timedelta(days=30 * months_elapsed)
        
        # Fallback to first of calendar month (legacy behavior)
        return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def get_invoices_this_period(self):
        """Get count of invoices uploaded this billing period"""
        from app.models.invoice import Invoice
        
        period_start = self.billing_period_start
        count = Invoice.query.filter(
            Invoice.user_id == self.id,
            Invoice.created_at >= period_start
        ).count()
        return count
    
    # Keep old method for backward compatibility but use new logic
    def get_invoices_this_month(self):
        """Get count of invoices uploaded this billing period (deprecated name)"""
        return self.get_invoices_this_period()
    
    @property
    def invoices_remaining(self):
        """Get remaining invoices for this billing period (including bonus)"""
        limit = self.monthly_invoice_limit
        if limit == float('inf'):
            return float('inf')
        
        used = self.get_invoices_this_period()
        base_remaining = max(0, limit - used)
        
        # Add bonus invoices
        bonus = self.bonus_invoices or 0
        
        return base_remaining + bonus
    
    @property
    def base_invoices_remaining(self):
        """Get remaining base invoices (excluding bonus)"""
        limit = self.monthly_invoice_limit
        if limit == float('inf'):
            return float('inf')
        used = self.get_invoices_this_period()
        return max(0, limit - used)
    
    @property
    def can_upload_invoice(self):
        """Check if user can upload more invoices"""
        if self.is_admin:
            return True
        if not self.has_active_subscription:
            return False
        return self.invoices_remaining > 0
    
    def use_invoice_quota(self, count=1):
        """
        Use invoice quota - deducts from bonus first, then base allowance.
        Returns True if quota was available, False if not.
        """
        if self.is_admin:
            return True
        
        if self.invoices_remaining < count:
            return False
        
        # Bonus invoices are used first (they're explicitly tracked)
        # Base allowance is implicitly tracked via invoice count
        # So we only need to deduct from bonus if base is exhausted
        base_remaining = self.base_invoices_remaining
        
        if base_remaining < count:
            # Need to use some bonus invoices
            bonus_needed = count - base_remaining
            self.bonus_invoices = max(0, (self.bonus_invoices or 0) - bonus_needed)
        
        return True
    
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
    
    @property
    def days_until_renewal(self):
        """Get days until subscription renews"""
        if not self.subscription_started_at:
            return None
        
        # Next renewal is subscription_started_at + 30 days from current period
        period_start = self.billing_period_start
        next_renewal = period_start + timedelta(days=30)
        days = (next_renewal - datetime.utcnow()).days
        return max(0, days)
    
    def __repr__(self):
        return f'<User {self.email}>'
