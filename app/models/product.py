"""Product model (QuickBooks cache)"""
from app.extensions import db
from datetime import datetime

class Product(db.Model):
    """Cached QuickBooks product"""
    id = db.Column(db.Integer, primary_key=True)
    
    # QuickBooks IDs
    qb_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    qb_sync_token = db.Column(db.String(50))
    
    # Product details
    name = db.Column(db.String(255), nullable=False)
    sku = db.Column(db.String(255), index=True)
    description = db.Column(db.Text)
    
    # Pricing
    unit_price = db.Column(db.Numeric(10, 2))
    purchase_cost = db.Column(db.Numeric(10, 2))
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced = db.Column(db.DateTime)
    
    def __repr__(self):
        return f'<Product {self.sku} - {self.name}>'
