"""
GoZappify Takeoff Models - Version 4
Enhanced with colour, gang count, and AI detection fields
"""

from app.extensions import db
from datetime import datetime


class TakeoffRoom(db.Model):
    """Room/zone on a drawing for grouping items."""
    __tablename__ = 'takeoff_room'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    points = db.Column(db.JSON)  # List of {x, y} points defining polygon
    floor_area = db.Column(db.Float)  # In pixels² (convert using scale)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    detections = db.relationship('TakeoffSymbolDetection', backref='room', lazy='dynamic')
    cable_runs = db.relationship('TakeoffCableRun', backref='room', lazy='dynamic')


class TakeoffSymbolTemplate(db.Model):
    """Template for a symbol to detect (linked to a product)."""
    __tablename__ = 'takeoff_symbol_template'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'))
    
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), default='other')
    description = db.Column(db.Text)  # Human description for AI
    
    # Template region on source document (for visual reference)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    
    # Link to QuickBooks/Xero product
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    
    # --- ENHANCED FIELDS FOR AI DETECTION ---
    
    # Colour distinction (for PIR sensors, etc.)
    colour = db.Column(db.String(30))  # blue, red, black, etc.
    
    # Text inside symbol (for S/M/H detectors)
    expected_text = db.Column(db.String(10))
    
    # Switch-specific fields
    gang_count = db.Column(db.Integer)  # 1, 2, 3, etc.
    is_dimmer = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    product = db.relationship('Product', backref='symbol_templates')
    detections = db.relationship('TakeoffSymbolDetection', backref='template', lazy='dynamic')


class TakeoffSymbolDetection(db.Model):
    """A detected instance of a symbol on a drawing."""
    __tablename__ = 'takeoff_symbol_detection'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey('takeoff_symbol_template.id'))
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    
    # Position on drawing
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    
    confidence = db.Column(db.Float, default=0.0)
    
    # --- AI DETECTION RESULTS ---
    
    # What the AI detected
    detected_text = db.Column(db.String(20))
    colour_detected = db.Column(db.String(30))
    gang_count_detected = db.Column(db.Integer)
    is_dimmer_detected = db.Column(db.Boolean)
    
    # AI notes/reasoning
    ai_notes = db.Column(db.Text)
    location_description = db.Column(db.String(200))  # "top-left of kitchen"
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    product = db.relationship('Product', backref='symbol_detections')


class TakeoffCableRun(db.Model):
    """A measured cable run on a drawing."""
    __tablename__ = 'takeoff_cable_run'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    
    start_x = db.Column(db.Float, nullable=False)
    start_y = db.Column(db.Float, nullable=False)
    end_x = db.Column(db.Float, nullable=False)
    end_y = db.Column(db.Float, nullable=False)
    
    length_metres = db.Column(db.Float)
    cable_type = db.Column(db.String(50))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TakeoffArea(db.Model):
    """A measured area on a drawing."""
    __tablename__ = 'takeoff_area'
    
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    
    name = db.Column(db.String(100))
    area_type = db.Column(db.String(50))
    points = db.Column(db.JSON)
    area_m2 = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
