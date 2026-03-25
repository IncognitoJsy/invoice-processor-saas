"""Customer Invoice model - invoices sent TO customers (full platform mode)"""
from app.extensions import db
from datetime import datetime, timedelta


class CustomerInvoice(db.Model):
    __tablename__ = 'customer_invoice'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    invoice_number = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='open')  # open, sent, paid, overdue
    invoice_mode = db.Column(db.String(20), default='itemised')  # itemised, summary
    payment_terms = db.Column(db.String(20), default='30')
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    subtotal = db.Column(db.Float, default=0.0)
    tax_rate = db.Column(db.Float, default=0.0)
    tax_amount = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', backref=db.backref('invoices', lazy='dynamic'))
    lines = db.relationship('CustomerInvoiceLine', backref='invoice', lazy='dynamic',
                            cascade='all, delete-orphan', order_by='CustomerInvoiceLine.sort_order')

    PAYMENT_TERMS = {
        'receipt': 'Due on Receipt',
        '0': 'Due on Receipt',
        '7': 'Net 7 Days',
        '14': 'Net 14 Days',
        '30': 'Net 30 Days',
        '60': 'Net 60 Days',
        'custom': 'Custom Date',
    }

    def calculate_due_date(self):
        if not self.issue_date:
            self.issue_date = datetime.utcnow()
        if self.payment_terms == 'receipt':
            self.due_date = self.issue_date
        elif self.payment_terms == 'custom':
            pass  # Set manually
        else:
            try:
                days = int(self.payment_terms)
                self.due_date = self.issue_date + timedelta(days=days)
            except (ValueError, TypeError):
                self.due_date = self.issue_date + timedelta(days=30)

    def recalculate_totals(self):
        lines = CustomerInvoiceLine.query.filter_by(customer_invoice_id=self.id).all()
        self.subtotal = sum(l.line_total or 0 for l in lines)
        self.tax_amount = round(self.subtotal * (self.tax_rate or 0) / 100, 2)
        self.total = round(self.subtotal + self.tax_amount, 2)

    @property
    def payment_terms_label(self):
        if self.payment_terms in self.PAYMENT_TERMS:
            return self.PAYMENT_TERMS[self.payment_terms]
        try:
            days = int(self.payment_terms or 30)
            if days == 0:
                return 'Due on Receipt'
            return f'Net {days} Days'
        except (ValueError, TypeError):
            return f'Net {self.payment_terms} Days'

    @property
    def is_overdue(self):
        if self.status in ['open', 'sent'] and self.due_date:
            from datetime import date, datetime
            due = self.due_date.date() if isinstance(self.due_date, datetime) else self.due_date
            return date.today() > due
        return False

    @property
    def days_overdue(self):
        if self.is_overdue and self.due_date:
            from datetime import date, datetime
            due = self.due_date.date() if isinstance(self.due_date, datetime) else self.due_date
            return (date.today() - due).days
        return 0

    def to_dict(self):
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'customer_id': self.customer_id,
            'customer_name': self.customer.display_name if self.customer else None,
            'status': self.status,
            'invoice_mode': self.invoice_mode,
            'payment_terms': self.payment_terms,
            'payment_terms_label': self.payment_terms_label,
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'subtotal': self.subtotal,
            'tax_rate': self.tax_rate,
            'tax_amount': self.tax_amount,
            'total': self.total,
            'notes': self.notes,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'lines': [l.to_dict() for l in self.lines],
        }

    def __repr__(self):
        return f'<CustomerInvoice {self.invoice_number}: {self.status}>'


class CustomerInvoiceLine(db.Model):
    __tablename__ = 'customer_invoice_line'

    id = db.Column(db.Integer, primary_key=True)
    customer_invoice_id = db.Column(db.Integer, db.ForeignKey('customer_invoice.id'),
                                    nullable=False, index=True)
    product_service_id = db.Column(db.Integer, db.ForeignKey('product_service.id'), nullable=True)
    source_invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=True)
    description = db.Column(db.String(500), nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)
    line_total = db.Column(db.Float, default=0.0)
    line_type = db.Column(db.String(20), default='itemised')  # itemised, summary
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'line_total': self.line_total,
            'line_type': self.line_type,
            'product_service_id': self.product_service_id,
            'source_invoice_id': self.source_invoice_id,
        }

    def __repr__(self):
        return f'<CustomerInvoiceLine {self.id}: {self.description}>'
