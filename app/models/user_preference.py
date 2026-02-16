"""User preferences and correction logging for Voice-to-Quote AI learning"""
from app.extensions import db
from datetime import datetime


class UserPreference(db.Model):
    """Per-user AI preferences — brand defaults, product swaps, circuit preferences, etc.
    
    Each preference is a single rule like:
    - category='brand_default', key='downlight', value='Aurora EN-DE52BZ/40'
    - category='product_swap', key='DLT5515000', value='EN-DE52BZ/40'
    - category='mounting_height', key='sockets', value='300'
    - category='circuit_preference', key='kitchen_sockets', value='radial'
    - category='general', key='back_box_depth', value='47mm'
    """
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)  # brand_default, product_swap, mounting_height, circuit_preference, general, supplier, cable_preference
    key = db.Column(db.String(200), nullable=False)       # what this preference is about
    value = db.Column(db.String(500), nullable=False)      # the preference value
    description = db.Column(db.String(500))                # human-readable explanation
    source = db.Column(db.String(20), default='chat')      # 'chat' = from Teach AI, 'auto' = promoted from corrections, 'manual' = settings form
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'category', 'key', name='uq_user_pref'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'key': self.key,
            'value': self.value,
            'description': self.description,
            'source': self.source,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def to_prompt_line(self):
        """Format this preference as a line for the AI prompt"""
        if self.category == 'brand_default':
            return f"- Default {self.key}: {self.value}"
        elif self.category == 'product_swap':
            return f"- When AI suggests {self.key}, use {self.value} instead"
        elif self.category == 'mounting_height':
            return f"- {self.key} mounting height: {self.value}mm FFL"
        elif self.category == 'circuit_preference':
            return f"- {self.key}: {self.value}"
        elif self.category == 'supplier':
            return f"- Preferred supplier for {self.key}: {self.value}"
        elif self.category == 'cable_preference':
            return f"- Cable preference for {self.key}: {self.value}"
        else:
            return f"- {self.key}: {self.value}"


class CorrectionLog(db.Model):
    """Logs every edit a user makes on parsed results.
    
    Used for:
    1. Tracking what the AI gets wrong per-user
    2. Auto-promoting repeated corrections to UserPreference
    3. Analytics on knowledge base gaps
    """
    __tablename__ = 'correction_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    job_title = db.Column(db.String(200))                  # which job this was from
    room_name = db.Column(db.String(100))                  # which room
    field_type = db.Column(db.String(50), nullable=False)  # 'product', 'quantity', 'part_number', 'back_box', 'cable', 'flag_resolution'
    original_value = db.Column(db.String(500))             # what the AI said
    corrected_value = db.Column(db.String(500))            # what the user changed it to
    context = db.Column(db.String(500))                    # extra context (e.g. the accessory description)
    correction_count = db.Column(db.Integer, default=1)    # how many times this exact correction has happened
    promoted = db.Column(db.Boolean, default=False)        # whether this has been auto-promoted to a preference
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'job_title': self.job_title,
            'room_name': self.room_name,
            'field_type': self.field_type,
            'original_value': self.original_value,
            'corrected_value': self.corrected_value,
            'context': self.context,
            'correction_count': self.correction_count,
            'promoted': self.promoted,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ProductCache(db.Model):
    """Cached products from Xero/QuickBooks — avoids hitting the API on every match.
    
    Refreshed on demand (manual sync) or when cache is stale (>24h).
    Stores the full product list per user for fast client-side searching.
    """
    __tablename__ = 'product_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    product_id = db.Column(db.String(200))                  # Xero ItemID or QB Item Id
    code = db.Column(db.String(200), index=True)            # Product/SKU code
    name = db.Column(db.String(500))                        # Product name
    description = db.Column(db.Text)                        # Sales description
    purchase_description = db.Column(db.Text)               # Purchase/supplier description
    purchase_price = db.Column(db.Float, default=0)
    sale_price = db.Column(db.Float, default=0)
    source = db.Column(db.String(20))                       # 'xero' or 'quickbooks'
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Index for fast code lookups per user
    __table_args__ = (
        db.Index('ix_product_cache_user_code', 'user_id', 'code'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'purchase_description': self.purchase_description,
            'purchase_price': self.purchase_price,
            'sale_price': self.sale_price,
            'source': self.source,
            'synced_at': self.synced_at.isoformat() if self.synced_at else None,
        }
