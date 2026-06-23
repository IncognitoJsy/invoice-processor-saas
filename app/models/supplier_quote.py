"""Supplier Quote Comparison models"""
from app.extensions import db
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres (matches prod — risk #10 reconciliation), plain JSON on SQLite (tests).
_JSONB = db.JSON().with_variant(JSONB, 'postgresql')


class SupplierQuoteSession(db.Model):
    __tablename__ = 'supplier_quote_session'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    job_card_id = db.Column(db.Integer, db.ForeignKey('job_card.id'), nullable=True, index=True)
    name = db.Column(db.String(255))
    status = db.Column(db.String(20), default='comparing')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    quotes = db.relationship('SupplierQuote', backref='session', lazy='dynamic',
                             cascade='all, delete-orphan')
    items = db.relationship('SupplierQuoteItem', backref='session', lazy='dynamic',
                            cascade='all, delete-orphan')

    @property
    def quote_count(self):
        return self.quotes.count()

    @property
    def item_count(self):
        return self.items.count()


class SupplierQuote(db.Model):
    __tablename__ = 'supplier_quote'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('supplier_quote_session.id'),
                           nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    supplier_name = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    raw_text = db.Column(db.Text)
    parsed_items = db.Column(_JSONB)
    status = db.Column(db.String(20), default='processing')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SupplierQuoteItem(db.Model):
    __tablename__ = 'supplier_quote_item'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('supplier_quote_session.id'),
                           nullable=False, index=True)
    generic_description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Numeric(10, 2), default=1)
    unit = db.Column(db.String(50))
    supplier_data = db.Column(_JSONB)  # {supplier_name: {price, part_no, description}}
    best_price_supplier = db.Column(db.String(255))
    best_price = db.Column(db.Numeric(10, 2))
    highest_price = db.Column(db.Numeric(10, 2))
    markup_base = db.Column(db.Numeric(10, 2))
    customer_price = db.Column(db.Numeric(10, 2))
    selected_supplier = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'generic_description': self.generic_description,
            'quantity': float(self.quantity or 1),
            'unit': self.unit,
            'supplier_data': self.supplier_data or {},
            'best_price_supplier': self.best_price_supplier,
            'best_price': float(self.best_price or 0),
            'highest_price': float(self.highest_price or 0),
            'markup_base': float(self.markup_base or 0),
            'customer_price': float(self.customer_price or 0),
            'selected_supplier': self.selected_supplier,
            'notes': self.notes,
        }
