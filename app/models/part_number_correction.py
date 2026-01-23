"""Part Number Correction Model - Learns from user corrections to improve OCR accuracy"""
from app.extensions import db
from datetime import datetime
from sqlalchemy import Index


class PartNumberCorrection(db.Model):
    """
    Stores learned part number corrections from user edits.
    When a user corrects an OCR-misread part number, we remember the mapping
    so future invoices with the same error are auto-corrected.
    """
    __tablename__ = 'part_number_correction'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # User who made the correction (corrections are user-specific initially)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('part_corrections', lazy='dynamic'))
    
    # The supplier context (corrections may be supplier-specific)
    supplier_name = db.Column(db.String(255), index=True)
    
    # The correction mapping
    original_ocr = db.Column(db.String(100), nullable=False, index=True)  # What Claude read (wrong)
    corrected_part = db.Column(db.String(100), nullable=False, index=True)  # What user corrected to
    
    # Track usage for confidence
    times_applied = db.Column(db.Integer, default=0)  # How many times this correction was auto-applied
    times_confirmed = db.Column(db.Integer, default=1)  # How many times user made this same correction
    
    # Source tracking
    source_invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))  # First invoice where correction was made
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_applied_at = db.Column(db.DateTime)  # Last time this correction was auto-applied
    
    # Status
    is_active = db.Column(db.Boolean, default=True)  # Can be disabled if user realizes it was wrong
    
    def __repr__(self):
        return f'<PartNumberCorrection "{self.original_ocr}" -> "{self.corrected_part}">'
    
    def to_dict(self):
        return {
            'id': self.id,
            'original_ocr': self.original_ocr,
            'corrected_part': self.corrected_part,
            'supplier_name': self.supplier_name,
            'times_applied': self.times_applied,
            'times_confirmed': self.times_confirmed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active
        }
    
    @classmethod
    def get_correction(cls, user_id: int, original_ocr: str, supplier_name: str = None):
        """
        Look up if we have a learned correction for this OCR result.
        Checks supplier-specific first, then falls back to general.
        """
        original_upper = original_ocr.upper().strip()
        
        # Try supplier-specific correction first
        if supplier_name:
            correction = cls.query.filter_by(
                user_id=user_id,
                original_ocr=original_upper,
                supplier_name=supplier_name,
                is_active=True
            ).first()
            
            if correction:
                return correction
        
        # Fall back to general correction (no supplier specified)
        correction = cls.query.filter_by(
            user_id=user_id,
            original_ocr=original_upper,
            is_active=True
        ).filter(
            (cls.supplier_name == None) | (cls.supplier_name == '')
        ).first()
        
        return correction
    
    @classmethod
    def add_or_update_correction(cls, user_id: int, original_ocr: str, corrected_part: str, 
                                  supplier_name: str = None, invoice_id: int = None):
        """
        Add a new correction or update existing one (increment confirmation count).
        """
        original_upper = original_ocr.upper().strip()
        corrected_upper = corrected_part.upper().strip()
        
        # Don't save if they're the same
        if original_upper == corrected_upper:
            return None
        
        # Check if this correction already exists
        existing = cls.query.filter_by(
            user_id=user_id,
            original_ocr=original_upper,
            corrected_part=corrected_upper,
            supplier_name=supplier_name
        ).first()
        
        if existing:
            # Increment confirmation count
            existing.times_confirmed += 1
            existing.updated_at = datetime.utcnow()
            existing.is_active = True  # Re-activate if it was disabled
            db.session.commit()
            return existing
        
        # Check if there's a different correction for the same original
        # If user is changing their mind, update instead of creating new
        different_correction = cls.query.filter_by(
            user_id=user_id,
            original_ocr=original_upper,
            supplier_name=supplier_name,
            is_active=True
        ).first()
        
        if different_correction:
            # User is changing the correction - update it
            different_correction.corrected_part = corrected_upper
            different_correction.times_confirmed = 1
            different_correction.updated_at = datetime.utcnow()
            db.session.commit()
            return different_correction
        
        # Create new correction
        correction = cls(
            user_id=user_id,
            original_ocr=original_upper,
            corrected_part=corrected_upper,
            supplier_name=supplier_name,
            source_invoice_id=invoice_id
        )
        
        db.session.add(correction)
        db.session.commit()
        
        return correction
    
    @classmethod
    def get_all_corrections_for_user(cls, user_id: int, supplier_name: str = None):
        """
        Get all active corrections for a user, optionally filtered by supplier.
        Returns a dict for quick lookup: {original_ocr: corrected_part}
        """
        query = cls.query.filter_by(user_id=user_id, is_active=True)
        
        if supplier_name:
            # Include both supplier-specific and general corrections
            query = query.filter(
                (cls.supplier_name == supplier_name) | 
                (cls.supplier_name == None) | 
                (cls.supplier_name == '')
            )
        
        corrections = query.all()
        
        # Build lookup dict - supplier-specific takes precedence
        lookup = {}
        for c in corrections:
            if c.original_ocr not in lookup:
                lookup[c.original_ocr] = c.corrected_part
            elif c.supplier_name == supplier_name:
                # Supplier-specific overrides general
                lookup[c.original_ocr] = c.corrected_part
        
        return lookup
    
    def mark_applied(self):
        """Mark this correction as having been auto-applied"""
        self.times_applied += 1
        self.last_applied_at = datetime.utcnow()
        db.session.commit()


# Indexes for fast lookups
Index('idx_correction_user_ocr', PartNumberCorrection.user_id, PartNumberCorrection.original_ocr)
Index('idx_correction_supplier', PartNumberCorrection.supplier_name)
Index('idx_correction_active', PartNumberCorrection.is_active)
