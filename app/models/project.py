"""Project models for Quote Builder - electrical takeoff and estimation"""
from app.extensions import db
from datetime import datetime
from sqlalchemy import Index
from sqlalchemy.dialects.postgresql import JSONB
import uuid

# JSONB on Postgres (matches prod — risk #10 reconciliation), plain JSON on SQLite (tests).
_JSONB = db.JSON().with_variant(JSONB, 'postgresql')


class Project(db.Model):
    """A quotation project - contains drawings, materials, and labour estimates"""
    __tablename__ = 'project'
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    
    # User relationship
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref=db.backref('projects', lazy='dynamic'))
    
    # Project details
    name = db.Column(db.String(255), nullable=False)
    client_name = db.Column(db.String(255))
    client_email = db.Column(db.String(255))
    client_phone = db.Column(db.String(50))
    site_address = db.Column(db.Text)
    
    # Project settings
    supply_type = db.Column(db.String(20), default='single_phase')  # single_phase, three_phase
    building_type = db.Column(db.String(50), default='renovation')  # new_build, renovation, retrofit, listed
    
    # Markup and labour settings
    materials_markup_percent = db.Column(db.Numeric(5, 2), default=25.0)
    labour_rate_per_hour = db.Column(db.Numeric(10, 2), default=45.0)
    contingency_percent = db.Column(db.Numeric(5, 2), default=10.0)
    
    # Calculated totals (updated when materials/labour change)
    total_materials_cost = db.Column(db.Numeric(12, 2), default=0)
    total_materials_sell = db.Column(db.Numeric(12, 2), default=0)
    total_labour_hours = db.Column(db.Numeric(10, 2), default=0)
    total_labour_cost = db.Column(db.Numeric(12, 2), default=0)
    subtotal = db.Column(db.Numeric(12, 2), default=0)
    contingency_amount = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)
    
    # Status
    status = db.Column(db.String(50), default='draft', index=True)  # draft, quoted, sent, won, lost
    
    # Quote validity
    quote_valid_days = db.Column(db.Integer, default=30)
    quoted_at = db.Column(db.DateTime)
    
    # QuickBooks sync
    qb_estimate_id = db.Column(db.String(50))
    qb_estimate_synced_at = db.Column(db.DateTime)
    qb_customer_id = db.Column(db.String(50))
    qb_customer_name = db.Column(db.String(255))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    documents = db.relationship('ProjectDocument', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    materials = db.relationship('ProjectMaterial', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    labour = db.relationship('ProjectLabour', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Project {self.name} - {self.status}>'
    
    def recalculate_totals(self):
        """Recalculate all project totals from materials and labour"""
        # Materials
        materials = ProjectMaterial.query.filter_by(project_id=self.id).all()
        self.total_materials_cost = sum(float(m.total_cost or 0) for m in materials)
        self.total_materials_sell = sum(float(m.total_sell or 0) for m in materials)
        
        # Labour
        labour = ProjectLabour.query.filter_by(project_id=self.id).all()
        self.total_labour_hours = sum(float(l.hours or 0) for l in labour)
        self.total_labour_cost = sum(float(l.total or 0) for l in labour)
        
        # Totals
        self.subtotal = self.total_materials_sell + self.total_labour_cost
        self.contingency_amount = self.subtotal * (float(self.contingency_percent or 0) / 100)
        self.grand_total = self.subtotal + self.contingency_amount
    
    def to_dict(self):
        return {
            'id': self.id,
            'uuid': self.uuid,
            'name': self.name,
            'client_name': self.client_name,
            'client_email': self.client_email,
            'site_address': self.site_address,
            'supply_type': self.supply_type,
            'building_type': self.building_type,
            'materials_markup_percent': float(self.materials_markup_percent or 0),
            'labour_rate_per_hour': float(self.labour_rate_per_hour or 0),
            'contingency_percent': float(self.contingency_percent or 0),
            'total_materials_cost': float(self.total_materials_cost or 0),
            'total_materials_sell': float(self.total_materials_sell or 0),
            'total_labour_hours': float(self.total_labour_hours or 0),
            'total_labour_cost': float(self.total_labour_cost or 0),
            'subtotal': float(self.subtotal or 0),
            'contingency_amount': float(self.contingency_amount or 0),
            'grand_total': float(self.grand_total or 0),
            'status': self.status,
            'quote_valid_days': self.quote_valid_days,
            'qb_estimate_id': self.qb_estimate_id,
            'qb_customer_name': self.qb_customer_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'documents_count': self.documents.count(),
            'materials_count': self.materials.count(),
        }


class ProjectDocument(db.Model):
    """Uploaded drawings and specifications for a project"""
    __tablename__ = 'project_document'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    
    # File details
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(500))
    file_size = db.Column(db.Integer)  # bytes
    mime_type = db.Column(db.String(100))
    
    # Document classification
    document_type = db.Column(db.String(50), default='drawing')  # drawing, schedule, spec, other
    floor_level = db.Column(db.String(50))  # ground, first, second, basement, etc.
    system_type = db.Column(db.String(50))  # lighting, power, data, fire_alarm, all
    
    # Parsing status
    parsed = db.Column(db.Boolean, default=False)
    # V8 takeoff canvas state (JSON blob)
    takeoff_v8_state = db.Column(_JSONB, nullable=True)
    parsed_at = db.Column(db.DateTime)
    parse_error = db.Column(db.Text)
    
    # Extracted metadata
    scale = db.Column(db.String(20))  # e.g., "1:50", "1:100"
    drawing_number = db.Column(db.String(100))
    revision = db.Column(db.String(20))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'document_type': self.document_type,
            'floor_level': self.floor_level,
            'system_type': self.system_type,
            'parsed': self.parsed,
            'parsed_at': self.parsed_at.isoformat() if self.parsed_at else None,
            'parse_error': self.parse_error,
            'scale': self.scale,
            'drawing_number': self.drawing_number,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ProjectMaterial(db.Model):
    """Material line item for a project - extracted from drawings or manually added"""
    __tablename__ = 'project_material'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    
    # Source tracking
    source_document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'))
    source_document = db.relationship('ProjectDocument')
    manually_added = db.Column(db.Boolean, default=False)
    
    # Category for grouping
    category = db.Column(db.String(100), index=True)  # distribution, cable, accessories, lighting, etc.
    
    # Product details
    part_number = db.Column(db.String(100), index=True)
    description = db.Column(db.Text)
    manufacturer = db.Column(db.String(100))
    
    # Quantities
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=1)
    unit = db.Column(db.String(20), default='each')  # each, m, box, roll, etc.
    
    # Pricing - cost (what you pay)
    unit_cost = db.Column(db.Numeric(10, 4))
    total_cost = db.Column(db.Numeric(12, 2))
    
    # Pricing - sell (what you charge)
    markup_percent = db.Column(db.Numeric(5, 2))
    unit_sell = db.Column(db.Numeric(10, 4))
    total_sell = db.Column(db.Numeric(12, 2))
    
    # Price source tracking
    price_source = db.Column(db.String(50))  # quickbooks, xero, supplier_quote, manual, estimated
    price_verified = db.Column(db.Boolean, default=False)
    price_date = db.Column(db.DateTime)
    
    # QuickBooks matching
    qb_item_id = db.Column(db.String(50))
    qb_item_name = db.Column(db.String(255))
    
    # Notes
    notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def calculate_totals(self, markup_percent=None):
        """Calculate total cost and sell prices"""
        qty = float(self.quantity or 0)
        unit_cost = float(self.unit_cost or 0)
        
        self.total_cost = round(qty * unit_cost, 2)
        
        if markup_percent is not None:
            self.markup_percent = markup_percent
        
        markup = float(self.markup_percent or 0)
        self.unit_sell = round(unit_cost * (1 + markup / 100), 4)
        self.total_sell = round(qty * float(self.unit_sell), 2)
    
    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'part_number': self.part_number,
            'description': self.description,
            'manufacturer': self.manufacturer,
            'quantity': float(self.quantity or 0),
            'unit': self.unit,
            'unit_cost': float(self.unit_cost or 0) if self.unit_cost else None,
            'total_cost': float(self.total_cost or 0) if self.total_cost else None,
            'markup_percent': float(self.markup_percent or 0) if self.markup_percent else None,
            'unit_sell': float(self.unit_sell or 0) if self.unit_sell else None,
            'total_sell': float(self.total_sell or 0) if self.total_sell else None,
            'price_source': self.price_source,
            'price_verified': self.price_verified,
            'qb_item_id': self.qb_item_id,
            'qb_item_name': self.qb_item_name,
            'manually_added': self.manually_added,
            'notes': self.notes,
        }


class ProjectLabour(db.Model):
    """Labour line item for a project"""
    __tablename__ = 'project_labour'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    
    # Task details
    task = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Time and cost
    hours = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    rate = db.Column(db.Numeric(10, 2))  # If different from project default
    total = db.Column(db.Numeric(12, 2))
    
    # Calculation source
    auto_calculated = db.Column(db.Boolean, default=True)
    calculation_basis = db.Column(db.Text)  # e.g., "54 downlights × 0.5 hrs"
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def calculate_total(self, default_rate=None):
        """Calculate total cost"""
        rate = float(self.rate or default_rate or 45)
        self.total = round(float(self.hours or 0) * rate, 2)
    
    def to_dict(self):
        return {
            'id': self.id,
            'task': self.task,
            'description': self.description,
            'hours': float(self.hours or 0),
            'rate': float(self.rate or 0) if self.rate else None,
            'total': float(self.total or 0) if self.total else None,
            'auto_calculated': self.auto_calculated,
            'calculation_basis': self.calculation_basis,
        }


class SupplierQuoteRequest(db.Model):
    """Track supplier quote requests sent from a project"""
    __tablename__ = 'supplier_quote_request'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    project = db.relationship('Project', backref=db.backref('quote_requests', lazy='dynamic'))
    
    # Supplier details
    supplier_name = db.Column(db.String(100), nullable=False)
    supplier_email = db.Column(db.String(255))
    
    # Request details
    category = db.Column(db.String(100))  # Which category of materials
    items_count = db.Column(db.Integer)
    
    # Status
    status = db.Column(db.String(50), default='pending')  # pending, sent, received, applied
    sent_at = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime)
    
    # Response tracking
    response_file_path = db.Column(db.String(500))
    response_total = db.Column(db.Numeric(12, 2))
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'supplier_name': self.supplier_name,
            'category': self.category,
            'items_count': self.items_count,
            'status': self.status,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'response_total': float(self.response_total) if self.response_total else None,
        }


# Indexes for common queries
Index('idx_project_user_status', Project.user_id, Project.status)
Index('idx_project_user_created', Project.user_id, Project.created_at.desc())
Index('idx_material_project_category', ProjectMaterial.project_id, ProjectMaterial.category)
Index('idx_material_part_number', ProjectMaterial.part_number)
