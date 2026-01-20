"""Invoice and InvoiceItem models - enhanced for parsed invoice storage"""
from app.extensions import db
from datetime import datetime
from sqlalchemy import Index

class Invoice(db.Model):
    """Stored parsed invoice or quote"""
    __tablename__ = 'invoice'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # User relationship
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('invoices', lazy='dynamic'))
    
    # Document type: 'invoice' or 'quote'
    document_type = db.Column(db.String(20), default='invoice', index=True)
    
    # Supplier info
    supplier_name = db.Column(db.String(255), nullable=False, index=True)
    supplier_email = db.Column(db.String(255))
    
    # Invoice/Quote details
    invoice_number = db.Column(db.String(255), index=True)
    invoice_date = db.Column(db.Date)
    job_reference = db.Column(db.String(255), index=True)
    
    # File details
    pdf_filename = db.Column(db.String(255))
    pdf_path = db.Column(db.String(500))
    
    # Consolidated invoice tracking
    is_consolidated = db.Column(db.Boolean, default=False)
    order_number = db.Column(db.Integer)  # 1, 2, 3 for consolidated
    total_orders = db.Column(db.Integer)  # Total number of orders in PDF
    
    # Financial totals
    total_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # What you paid
    total_selling = db.Column(db.Numeric(10, 2))  # What you charge customer
    total_profit = db.Column(db.Numeric(10, 2))  # Your profit
    average_markup = db.Column(db.Numeric(5, 2))  # Average markup %
    
    items_count = db.Column(db.Integer, default=0)
    
    # Parser metadata
    parser_method = db.Column(db.String(50))  # 'claude_api', 'custom_yesss', 'both_agreed'
    confidence = db.Column(db.String(20))  # 'high', 'medium', 'low'
    needs_review = db.Column(db.Boolean, default=False)
    
    # Processing status
    status = db.Column(db.String(50), default='completed', index=True)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    error_message = db.Column(db.Text)
    
    # QuickBooks sync - for invoices
    qb_bill_id = db.Column(db.String(50))
    qb_synced_at = db.Column(db.DateTime)
    
    # QuickBooks sync - for quotes/estimates
    qb_estimate_id = db.Column(db.String(50))
    qb_estimate_synced_at = db.Column(db.DateTime)
    
    # Xero sync - for invoices
    xero_invoice_id = db.Column(db.String(50))
    xero_synced_at = db.Column(db.DateTime)
    
    # Xero sync - for quotes
    xero_quote_id = db.Column(db.String(50))
    xero_quote_synced_at = db.Column(db.DateTime)
    
    # Customer matching (for quotes that become estimates)
    matched_customer_id = db.Column(db.String(50))  # QB Customer ID
    matched_customer_name = db.Column(db.String(255))  # QB Customer Name
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('InvoiceItem', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        doc_type = self.document_type or 'invoice'
        return f'<{doc_type.title()} {self.supplier_name} - {self.job_reference} - £{self.total_cost}>'
    
    @property
    def is_quote(self):
        return self.document_type == 'quote'
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'document_type': self.document_type or 'invoice',
            'supplier_name': self.supplier_name,
            'invoice_number': self.invoice_number,
            'job_reference': self.job_reference,
            'total_cost': float(self.total_cost) if self.total_cost else 0,
            'total_selling': float(self.total_selling) if self.total_selling else 0,
            'total_profit': float(self.total_profit) if self.total_profit else 0,
            'items_count': self.items_count,
            'confidence': self.confidence,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_consolidated': self.is_consolidated,
            'order_number': self.order_number,
            'qb_bill_id': self.qb_bill_id,
            'qb_synced_at': self.qb_synced_at.isoformat() if self.qb_synced_at else None,
            'qb_estimate_id': self.qb_estimate_id,
            'qb_estimate_synced_at': self.qb_estimate_synced_at.isoformat() if self.qb_estimate_synced_at else None,
            'xero_invoice_id': self.xero_invoice_id,
            'xero_synced_at': self.xero_synced_at.isoformat() if self.xero_synced_at else None,
            'xero_quote_id': self.xero_quote_id,
            'xero_quote_synced_at': self.xero_quote_synced_at.isoformat() if self.xero_quote_synced_at else None,
            'matched_customer_id': self.matched_customer_id,
            'matched_customer_name': self.matched_customer_name
        }


class InvoiceItem(db.Model):
    """Individual line item from an invoice or quote"""
    __tablename__ = 'invoice_item'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False, index=True)
    
    # Product details
    part_number = db.Column(db.String(100), index=True)
    description = db.Column(db.Text)
    
    # Quantities and pricing
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    cost_per_item = db.Column(db.Numeric(10, 4), nullable=False)  # Your cost
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)   # qty * cost
    
    # Selling price (with markup)
    selling_price = db.Column(db.Numeric(10, 4))  # Price per item you charge
    profit_per_item = db.Column(db.Numeric(10, 4))  # selling - cost per item
    
    def __repr__(self):
        return f'<InvoiceItem {self.part_number}: {self.quantity} x £{self.cost_per_item}>'
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
            'part_number': self.part_number,
            'description': self.description,
            'quantity': float(self.quantity),
            'cost_per_item': float(self.cost_per_item),
            'total_amount': float(self.total_amount),
            'selling_price': float(self.selling_price) if self.selling_price else 0,
            'profit_per_item': float(self.profit_per_item) if self.profit_per_item else 0
        }


# Create indexes for common queries
Index('idx_invoice_user_created', Invoice.user_id, Invoice.created_at.desc())
Index('idx_invoice_supplier_date', Invoice.supplier_name, Invoice.created_at.desc())
Index('idx_invoice_job_ref', Invoice.job_reference)
Index('idx_invoice_doc_type', Invoice.document_type)
Index('idx_item_part_number', InvoiceItem.part_number)
