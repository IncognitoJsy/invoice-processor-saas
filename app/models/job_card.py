"""Job Card model - links customers, supplier invoices, customer invoices and quotes"""
from app.extensions import db
from datetime import datetime


class JobCard(db.Model):
    __tablename__ = 'job_card'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='new')
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('customer_quote.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', backref='job_cards', lazy='select')
    # Pin to quote_id: customer_quote.job_card_id (adopted from prod, risk #10) adds a 2nd FK path.
    quote = db.relationship('CustomerQuote', backref='job_card', lazy='select', foreign_keys=[quote_id])

    STATUSES = {
        'new': 'New',
        'in_progress': 'In Progress',
        'complete': 'Complete',
        'invoiced': 'Invoiced',
        'paid': 'Paid',
    }

    @property
    def status_label(self):
        return self.STATUSES.get(self.status, self.status.title())

    @property
    def supplier_invoices(self):
        from app.models.invoice import Invoice
        return Invoice.query.filter_by(job_card_id=self.id).all()

    @property
    def customer_invoices(self):
        from app.models.customer_invoice import CustomerInvoice
        return CustomerInvoice.query.filter_by(job_card_id=self.id).all()

    @property
    def total_materials(self):
        return sum(float(i.total_cost or 0) for i in self.supplier_invoices)

    @property
    def total_invoiced(self):
        return sum(float(i.total or 0) for i in self.customer_invoices if i.status != 'void')

    @property
    def total_paid(self):
        return sum(float(i.total or 0) for i in self.customer_invoices if i.status == 'paid')

    @property
    def profit(self):
        return self.total_invoiced - self.total_materials

    @property
    def quote_total(self):
        return float(self.quote.total) if self.quote and self.quote.total else 0
