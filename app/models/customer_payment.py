"""Customer Payment model - records payments against customer invoices"""
from app.extensions import db
from datetime import datetime


class CustomerPayment(db.Model):
    __tablename__ = 'customer_payment'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    payment_method = db.Column(db.String(50), default='bank_transfer')
    reference = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship('Customer', backref='payments', lazy='select')
    invoice_payments = db.relationship('CustomerInvoicePayment', backref='payment',
                                       cascade='all, delete-orphan', lazy='dynamic')

    PAYMENT_METHODS = {
        'bank_transfer': 'Bank Transfer',
        'faster_payments': 'Faster Payments',
        'bacs': 'BACS',
        'cash': 'Cash',
        'cheque': 'Cheque',
        'card': 'Card',
        'other': 'Other',
    }

    @property
    def method_label(self):
        return self.PAYMENT_METHODS.get(self.payment_method, self.payment_method.title())


class CustomerInvoicePayment(db.Model):
    """Junction table linking payments to invoices"""
    __tablename__ = 'customer_invoice_payment'

    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('customer_payment.id'), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('customer_invoice.id'), nullable=False)
    amount_applied = db.Column(db.Numeric(12, 2), nullable=False)

    invoice = db.relationship('CustomerInvoice', backref='payment_links', lazy='select')
