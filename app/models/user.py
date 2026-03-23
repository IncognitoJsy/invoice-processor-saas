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
    billing_frequency = db.Column(db.String(10), default='monthly')  # monthly, annual
    subscription_status = db.Column(db.String(20), default='active')  # active, past_due, suspended, cancelled, expired
    
    # PayPal fields
    paypal_subscription_id = db.Column(db.String(255))
    pending_subscription_id = db.Column(db.String(255))
    
    # Legacy fields (keep for backwards compatibility)
    paddle_customer_id = db.Column(db.String(255))
    paddle_subscription_id = db.Column(db.String(255))
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    
    trial_ends_at = db.Column(db.DateTime)
    subscription_ends_at = db.Column(db.DateTime)
    subscription_started_at = db.Column(db.DateTime)
    
    # Bonus invoices (purchased top-ups)
    bonus_invoices = db.Column(db.Integer, default=0)

    # Setup wizard & onboarding
    setup_completed = db.Column(db.Boolean, default=False)
    tour_completed = db.Column(db.Boolean, default=False)
    company_name = db.Column(db.String(255))
    default_markup = db.Column(db.Float, default=50.0)
    # Platform mode & trade (multi-trade expansion)
    platform_mode = db.Column(db.String(20), default='sync')  # sync, full, both
    trade_type = db.Column(db.String(50))
    country = db.Column(db.String(50))

    # Bank / payment details (full platform mode)
    logo_url = db.Column(db.String(500))
    invoice_colour = db.Column(db.String(20), default='#2563eb')
    bank_name = db.Column(db.String(100))
    bank_account_name = db.Column(db.String(100))
    bank_account_number = db.Column(db.String(50))
    bank_sort_code = db.Column(db.String(20))
    bank_iban = db.Column(db.String(50))
    invoice_prefix = db.Column(db.String(10), default='INV')
    quote_prefix = db.Column(db.String(10), default='QUO')
    next_invoice_number = db.Column(db.Integer, default=1)
    next_quote_number = db.Column(db.Integer, default=1)
    default_payment_terms = db.Column(db.String(20), default='30')
    invoice_notes = db.Column(db.Text)
    default_invoice_mode = db.Column(db.String(20), default='itemised')

    # Tax / GST / VAT
    tax_registered = db.Column(db.Boolean, default=False)
    tax_number = db.Column(db.String(100))
    tax_type = db.Column(db.String(10))
    tax_rate = db.Column(db.Float, default=0.0)
    tax_registered_from = db.Column(db.DateTime)


    
    # Email notifications
    trial_reminder_sent = db.Column(db.Boolean, default=False)
    payment_failed_email_sent = db.Column(db.Boolean, default=False)
    
    # MFA (Multi-Factor Authentication)
    mfa_enabled = db.Column(db.Boolean, default=False)
    mfa_secret = db.Column(db.String(255))  # TOTP secret key (encrypted)
    mfa_recovery_codes = db.Column(db.Text)  # JSON list of hashed recovery codes
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_mfa_secret(self):
        """Generate a new TOTP secret for MFA setup"""
        import pyotp
        self.mfa_secret = pyotp.random_base32()
        return self.mfa_secret
    
    def get_mfa_uri(self):
        """Get the otpauth URI for QR code generation"""
        import pyotp
        if not self.mfa_secret:
            return None
        totp = pyotp.TOTP(self.mfa_secret)
        return totp.provisioning_uri(name=self.email, issuer_name='GoZappify')
    
    def verify_mfa_code(self, code):
        """Verify a TOTP code"""
        import pyotp
        if not self.mfa_secret:
            return False
        totp = pyotp.TOTP(self.mfa_secret)
        return totp.verify(code, valid_window=1)  # Allow 1 window tolerance (30 sec each side)
    
    def generate_recovery_codes(self):
        """Generate 8 one-time recovery codes"""
        import secrets
        import json
        codes = [secrets.token_hex(4).upper() for _ in range(8)]  # e.g. 'A1B2C3D4'
        # Store hashed versions
        self.mfa_recovery_codes = json.dumps([
            generate_password_hash(code) for code in codes
        ])
        return codes  # Return plain codes to show user once
    
    def use_recovery_code(self, code):
        """Verify and consume a recovery code. Returns True if valid."""
        import json
        if not self.mfa_recovery_codes:
            return False
        
        hashed_codes = json.loads(self.mfa_recovery_codes)
        for i, hashed in enumerate(hashed_codes):
            if check_password_hash(hashed, code.upper().strip()):
                # Remove used code
                hashed_codes.pop(i)
                self.mfa_recovery_codes = json.dumps(hashed_codes)
                return True
        return False
    
    def disable_mfa(self):
        """Disable MFA and clear secrets"""
        self.mfa_enabled = False
        self.mfa_secret = None
        self.mfa_recovery_codes = None
    
    def start_trial(self):
        self.subscription_plan = 'trial'
        self.subscription_status = 'active'
        self.trial_ends_at = datetime.utcnow() + timedelta(days=7)
    
    def start_paid_subscription(self, plan='basic', frequency='monthly'):
        self.subscription_plan = plan
        self.billing_frequency = frequency
        self.subscription_status = 'active'
        self.subscription_started_at = datetime.utcnow()
        self.bonus_invoices = 0
        self.payment_failed_email_sent = False
    
    def renew_subscription(self):
        self.subscription_started_at = datetime.utcnow()
        self.subscription_status = 'active'
        self.payment_failed_email_sent = False
    
    def add_bonus_invoices(self, count):
        self.bonus_invoices = (self.bonus_invoices or 0) + count
    
    @property
    def is_trial_active(self):
        if self.subscription_plan != 'trial':
            return False
        if not self.trial_ends_at:
            return False
        return datetime.utcnow() < self.trial_ends_at
    
    @property
    def trial_days_remaining(self):
        if not self.trial_ends_at:
            return 0
        remaining = (self.trial_ends_at - datetime.utcnow()).days
        return max(0, remaining)
    
    @property
    def has_active_subscription(self):
        if self.is_admin:
            return True
        if self.subscription_plan in ['basic', 'pro'] and self.subscription_status in ['active', 'past_due']:
            return True
        if self.is_trial_active:
            return True
        return False
    
    @property
    def has_payment_issue(self):
        return self.subscription_status in ['suspended', 'past_due']
    
    @property
    def can_sync_to_accounting(self):
        if self.is_admin:
            return True
        if self.subscription_status == 'suspended':
            return False
        return self.has_active_subscription
    
    @property
    def monthly_invoice_limit(self):
        if self.is_admin:
            return float('inf')
        if self.subscription_plan == 'basic' and self.billing_frequency == 'annual':
            return 1200  # Annual basic gets 1200 per year
        limits = {'trial': 25, 'basic': 100, 'pro': float('inf'), 'ultimate': float('inf'), 'cancelled': 0}
        return limits.get(self.subscription_plan, 0)
    
    @property
    def billing_period_start(self):
        if self.subscription_plan == 'trial':
            return self.created_at
        
        if self.subscription_started_at:
            now = datetime.utcnow()
            start = self.subscription_started_at
            
            # Annual billing: period is 365 days
            if self.billing_frequency == 'annual':
                years_elapsed = 0
                while True:
                    next_period = start + timedelta(days=365 * (years_elapsed + 1))
                    if next_period > now:
                        break
                    years_elapsed += 1
                return start + timedelta(days=365 * years_elapsed)
            
            # Monthly billing: period is 30 days
            months_elapsed = 0
            while True:
                next_period = start + timedelta(days=30 * (months_elapsed + 1))
                if next_period > now:
                    break
                months_elapsed += 1
            return start + timedelta(days=30 * months_elapsed)
        
        return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def get_invoices_this_period(self):
        from app.models.invoice import Invoice
        period_start = self.billing_period_start
        return Invoice.query.filter(Invoice.user_id == self.id, Invoice.created_at >= period_start).count()
    
    def get_invoices_this_month(self):
        return self.get_invoices_this_period()
    
    @property
    def invoices_remaining(self):
        limit = self.monthly_invoice_limit
        if limit == float('inf'):
            return float('inf')
        used = self.get_invoices_this_period()
        base_remaining = max(0, limit - used)
        return base_remaining + (self.bonus_invoices or 0)
    
    @property
    def base_invoices_remaining(self):
        limit = self.monthly_invoice_limit
        if limit == float('inf'):
            return float('inf')
        used = self.get_invoices_this_period()
        return max(0, limit - used)
    
    @property
    def can_upload_invoice(self):
        if self.is_admin:
            return True
        if self.subscription_status == 'suspended':
            return False
        if self.subscription_status in ['expired', 'cancelled']:
            return False
        if self.subscription_plan == 'cancelled':
            return False
        if self.subscription_plan == 'trial' and not self.is_trial_active:
            return False
        if self.invoices_remaining <= 0:
            return False
        return True
    
    @property
    def upload_blocked_reason(self):
        if self.is_admin:
            return None
        if self.subscription_status == 'suspended':
            return 'payment_suspended'
        if self.subscription_status in ['expired', 'cancelled']:
            return 'subscription_ended'
        if self.subscription_plan == 'cancelled':
            return 'subscription_cancelled'
        if self.subscription_plan == 'trial' and not self.is_trial_active:
            return 'trial_expired'
        if self.invoices_remaining <= 0:
            return 'quota_exceeded'
        return None
    
    def use_invoice_quota(self, count=1):
        if self.is_admin:
            return True
        if self.invoices_remaining < count:
            return False
        base_remaining = self.base_invoices_remaining
        if base_remaining < count:
            bonus_needed = count - base_remaining
            self.bonus_invoices = max(0, (self.bonus_invoices or 0) - bonus_needed)
        return True
    
    @property 
    def plan_display_name(self):
        names = {'trial': 'Free Trial', 'basic': 'Basic', 'pro': 'Pro', 'ultimate': 'Ultimate', 'cancelled': 'Cancelled'}
        name = names.get(self.subscription_plan, 'Unknown')
        if self.billing_frequency == 'annual' and self.subscription_plan in ('basic', 'pro', 'ultimate'):
            name += ' (Annual)'
        return name
    
    @property
    def status_display_name(self):
        names = {'active': 'Active', 'past_due': 'Payment Pending', 'suspended': 'Suspended', 'cancelled': 'Cancelled', 'expired': 'Expired'}
        return names.get(self.subscription_status, 'Unknown')
    
    @property
    def days_until_renewal(self):
        if not self.subscription_started_at:
            return None
        period_start = self.billing_period_start
        period_days = 365 if self.billing_frequency == 'annual' else 30
        next_renewal = period_start + timedelta(days=period_days)
        return max(0, (next_renewal - datetime.utcnow()).days)
    
    def __repr__(self):
        return f'<User {self.email}>'
