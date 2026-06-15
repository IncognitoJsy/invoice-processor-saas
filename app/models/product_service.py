"""Products & Services catalogue model"""
from app.extensions import db
from datetime import datetime


class ProductService(db.Model):
    __tablename__ = 'product_service'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    sku = db.Column(db.String(100))
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    item_type = db.Column(db.String(20), default='product')  # product, service, labour
    purchase_price = db.Column(db.Numeric(10, 4), default=0)
    sale_price = db.Column(db.Numeric(10, 4), default=0)
    unit_of_measure = db.Column(db.String(50))
    tax_applicable = db.Column(db.Boolean, default=False)
    track_stock = db.Column(db.Boolean, default=False)
    quantity_in_stock = db.Column(db.Numeric(10, 3), default=0)
    low_stock_threshold = db.Column(db.Numeric(10, 3))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def margin_pct(self):
        if self.sale_price and self.purchase_price and self.sale_price > 0:
            return round(((self.sale_price - self.purchase_price) / self.sale_price) * 100, 1)
        return 0.0

    @property
    def markup_pct(self):
        if self.purchase_price and self.purchase_price > 0:
            return round(((self.sale_price - self.purchase_price) / self.purchase_price) * 100, 1)
        return 0.0

    def __repr__(self):
        return f'<ProductService {self.id}: {self.name}>'
