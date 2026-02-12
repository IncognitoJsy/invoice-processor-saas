"""Queued Invoice model - stores PDFs waiting to be processed"""
from app.extensions import db
from datetime import datetime


class QueuedInvoice(db.Model):
    """PDF invoices queued for processing - either manually uploaded or auto-fetched from email"""
    __tablename__ = 'queued_invoice'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # File info
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)  # bytes
    page_count = db.Column(db.Integer, default=1)
    
    # Source info (manual upload vs email fetch)
    source = db.Column(db.String(20), default='manual')  # 'manual' or 'email'
    source_email = db.Column(db.String(255))  # sender email if from email fetch
    supplier_name = db.Column(db.String(100))  # detected or user-assigned supplier
    email_subject = db.Column(db.String(500))  # email subject line
    email_received_date = db.Column(db.DateTime)  # when the email was received
    
    # Deduplication for email fetch
    email_message_id = db.Column(db.String(255))  # Gmail message ID
    attachment_hash = db.Column(db.String(64))  # SHA-256 of the PDF content
    
    # Status tracking
    status = db.Column(db.String(20), default='queued')  # queued, processing, completed, failed
    target_tab = db.Column(db.String(20))  # 'invoice' or 'quote' - set when user drags to process
    processed_invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = db.Column(db.DateTime)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('queued_invoices', lazy='dynamic'))
    
    def to_dict(self):
        """Convert to dictionary for JSON response"""
        return {
            'id': self.id,
            'filename': self.original_filename,
            'file_size': self.file_size,
            'file_size_display': self.file_size_display,
            'page_count': self.page_count,
            'source': self.source,
            'source_email': self.source_email,
            'supplier_name': self.supplier_name,
            'email_subject': self.email_subject,
            'status': self.status,
            'target_tab': self.target_tab,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'age_display': self.age_display
        }
    
    @property
    def file_size_display(self):
        """Human-readable file size"""
        if not self.file_size:
            return 'Unknown'
        if self.file_size < 1024:
            return f'{self.file_size} B'
        elif self.file_size < 1024 * 1024:
            return f'{self.file_size / 1024:.1f} KB'
        else:
            return f'{self.file_size / (1024 * 1024):.1f} MB'
    
    @property
    def age_display(self):
        """How long ago this was queued"""
        if not self.created_at:
            return 'Unknown'
        delta = datetime.utcnow() - self.created_at
        if delta.days > 0:
            return f'{delta.days}d ago'
        elif delta.seconds > 3600:
            return f'{delta.seconds // 3600}h ago'
        elif delta.seconds > 60:
            return f'{delta.seconds // 60}m ago'
        else:
            return 'Just now'
    
    @classmethod
    def already_fetched(cls, user_id, email_message_id, attachment_filename):
        """Check if we've already fetched this specific attachment from this email"""
        return cls.query.filter_by(
            user_id=user_id,
            email_message_id=email_message_id,
            original_filename=attachment_filename
        ).first() is not None
    
    def __repr__(self):
        return f'<QueuedInvoice {self.id}: {self.original_filename} ({self.status})>'
