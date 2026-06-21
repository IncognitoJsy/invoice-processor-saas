"""Customer Quote model for full platform mode"""
from app.extensions import db
from datetime import datetime
from app.utils.money import money, to_decimal
import secrets


class CustomerQuote(db.Model):
    __tablename__ = 'customer_quote'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    quote_number = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='draft')  # draft, sent, accepted, declined, expired, converted
    issue_date = db.Column(db.Date, default=datetime.utcnow)
    expiry_date = db.Column(db.Date, nullable=True)
    subtotal = db.Column(db.Numeric(12, 2), default=0)
    tax_rate = db.Column(db.Numeric(5, 2), default=0)
    tax_amount = db.Column(db.Numeric(12, 2), default=0)
    total = db.Column(db.Numeric(12, 2), default=0)
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    payment_terms = db.Column(db.String(20), default='30')
    acceptance_token = db.Column(db.String(64), unique=True, index=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    accepted_by_name = db.Column(db.String(255), nullable=True)
    converted_invoice_id = db.Column(db.Integer, db.ForeignKey('customer_invoice.id'), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship('Customer', backref='quotes', lazy='select')
    lines = db.relationship('CustomerQuoteLine', backref='quote', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='CustomerQuoteLine.sort_order')

    def generate_token(self):
        self.acceptance_token = secrets.token_urlsafe(32)

    def recalculate_totals(self):
        # Line-authority, Decimal end-to-end (ROUND_HALF_UP via money()).
        self.subtotal = money(sum((money(l.line_total or 0) for l in self.lines), to_decimal(0)))
        self.tax_amount = money(self.subtotal * to_decimal(self.tax_rate or 0) / 100)
        self.total = money(self.subtotal + self.tax_amount)

    @property
    def payment_terms_label(self):
        terms_map = {'7': 'Net 7 Days', '14': 'Net 14 Days', '30': 'Net 30 Days',
                     '60': 'Net 60 Days', '0': 'Due on Receipt'}
        return terms_map.get(str(self.payment_terms or '30'), f'Net {self.payment_terms} Days')

    @property
    def display_status(self):
        return {
            'draft': 'Draft', 'sent': 'Sent', 'accepted': 'Accepted',
            'declined': 'Declined', 'expired': 'Expired', 'converted': 'Converted'
        }.get(self.status, self.status.title())

    def to_dict(self):
        return {
            'id': self.id,
            'quote_number': self.quote_number,
            'status': self.status,
            'customer_name': self.customer.display_name if self.customer else '—',
            'issue_date': self.issue_date.isoformat() if self.issue_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'total': self.total,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
        }


class CustomerQuoteLine(db.Model):
    __tablename__ = 'customer_quote_line'

    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('customer_quote.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(10, 3), default=1)
    unit_price = db.Column(db.Numeric(10, 4), default=0)
    line_total = db.Column(db.Numeric(10, 2), default=0)
    sort_order = db.Column(db.Integer, default=0)

    def calculate_total(self):
        self.line_total = money(to_decimal(self.quantity or 0) * to_decimal(self.unit_price or 0))
