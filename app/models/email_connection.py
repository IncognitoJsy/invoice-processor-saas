"""Email Connection model - stores OAuth tokens for email monitoring"""
from app.extensions import db
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
import os
import json

# Marker stored in last_error when a stored token can no longer be decrypted
# (e.g. it was encrypted under a previous auto-generated key) and the user must
# reconnect the account. See needs_reconnect.
RECONNECT_REQUIRED = 'reconnect_required'


class EmailConnection(db.Model):
    """User's connected email account for auto-fetching invoices"""
    __tablename__ = 'email_connection'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Provider info
    provider = db.Column(db.String(20), nullable=False)  # 'gmail' or 'imap'
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

    # IMAP-specific fields
    imap_server = db.Column(db.String(255), nullable=True)
    imap_port = db.Column(db.Integer, nullable=True, default=993)
    use_ssl = db.Column(db.Boolean, nullable=True, default=True)

    # SMTP fields for sending (IMAP users)
    smtp_server = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True, default=587)
    smtp_use_tls = db.Column(db.Boolean, nullable=True, default=True)

    # SMTP fields for sending (IMAP users)
    smtp_server = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True, default=587)
    smtp_use_tls = db.Column(db.Boolean, nullable=True, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('email_connections', lazy='dynamic'))
    
    @staticmethod
    def _get_encryption_key():
        """Return the email-token encryption key from the environment.

        The key is validated at startup (AUDIT risk #3), so it is always set
        here. It is never auto-generated: an ephemeral key would silently brick
        every stored credential on the next restart.
        """
        key = os.environ.get('EMAIL_TOKEN_ENCRYPTION_KEY')
        if not key:
            raise RuntimeError('EMAIL_TOKEN_ENCRYPTION_KEY is not set')
        return key.encode() if isinstance(key, str) else key

    def set_token(self, token_data):
        """Encrypt and store OAuth token"""
        f = Fernet(self._get_encryption_key())
        token_json = json.dumps(token_data)
        self.encrypted_token = f.encrypt(token_json.encode()).decode()
        # A successful re-store clears any prior reconnect requirement.
        if self.last_error == RECONNECT_REQUIRED:
            self.last_error = None

    def get_token(self):
        """Decrypt and return the stored OAuth token.

        If the token cannot be decrypted (typically encrypted under a previous
        auto-generated key that is now lost), flag the connection for reconnect
        and return None instead of raising, so callers degrade gracefully.
        """
        if not self.encrypted_token:
            return None
        f = Fernet(self._get_encryption_key())
        try:
            token_json = f.decrypt(self.encrypted_token.encode()).decode()
        except InvalidToken:
            self.mark_needs_reconnect()
            return None
        return json.loads(token_json)

    def mark_needs_reconnect(self):
        """Deactivate the connection and flag that the user must reconnect."""
        self.is_active = False
        self.last_error = RECONNECT_REQUIRED
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    @property
    def needs_reconnect(self):
        """True if a decrypt failure means the user must re-authenticate."""
        return self.last_error == RECONNECT_REQUIRED
    
    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'email_address': self.email_address,
            'is_active': self.is_active,
            'needs_reconnect': self.needs_reconnect,
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
