"""Invoice model"""
from app.extensions import db
from datetime import datetime

class Invoice(db.Model):
    """Invoice queue item"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Supplier info
    supplier_name = db.Column(db.String(255), nullable=False, index=True)
    supplier_email = db.Column(db.String(255))
    
    # Invoice details
    invoice_number = db.Column(db.String(255))
    invoice_date = db.Column(db.Date)
    invoice_type = db.Column(db.String(50))  # 'invoice' or 'credit'
    
    # Job reference
    job_reference = db.Column(db.String(255), index=True)
    
    # File details
    pdf_path = db.Column(db.String(500))
    pdf_filename = db.Column(db.String(255))
    
    # Processing status
    status = db.Column(db.String(50), default='pending', index=True)
    # Status: pending, processing, completed, failed, skipped
    
    processed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)
    
    # Email metadata
    email_subject = db.Column(db.String(500))
    email_date = db.Column(db.DateTime)
    gmail_message_id = db.Column(db.String(255), unique=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Invoice {self.supplier_name} - {self.job_reference}>'
