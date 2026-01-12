"""Invoice and InvoiceItem models - enhanced for parsed invoice storage"""
from app.extensions import db
from datetime import datetime
from sqlalchemy import Index

class Invoice(db.Model):
    """Stored parsed invoice"""
    __tablename__ = 'invoice'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # User relationship
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('invoices', lazy='dynamic'))
    
    # Supplier info
    supplier_name = db.Column(db.String(255), nullable=False, index=True)
    supplier_email = db.Column(db.String(255))
    
    # Invoice details
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
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    items = db.relationship('InvoiceItem', backref='invoice', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Invoice {self.supplier_name} - {self.job_reference} - £{self.total_cost}>'
    
    def to_dict(self):
        """Convert to dictionary for JSON responses"""
        return {
            'id': self.id,
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
            'order_number': self.order_number
        }


class InvoiceItem(db.Model):
    """Individual line item from an invoice"""
    __tablename__ = 'invoice_item'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False, index=True)
    
    # Product details
    part_number = db.Column(db.String(255), index=True)
    description = db.Column(db.Text)
    
    # Quantities
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Pricing (from supplier)
    original_unit_price = db.Column(db.Numeric(10, 2))  # Before discount
    discount_percent = db.Column(db.Numeric(5, 2))  # Discount %
    cost_per_item = db.Column(db.Numeric(10, 2), nullable=False)  # After discount
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)  # Line total (cost)
    
    # Your pricing (to customer)
    selling_price = db.Column(db.Numeric(10, 2))  # Per unit
    markup_percent = db.Column(db.Numeric(5, 2))  # Your markup %
    profit_per_item = db.Column(db.Numeric(10, 2))  # Profit per unit
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<InvoiceItem {self.part_number} x{self.quantity}>'
    
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
Index('idx_item_part_number', InvoiceItem.part_number)
