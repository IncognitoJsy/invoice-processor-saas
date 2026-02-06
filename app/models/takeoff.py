"""Takeoff models for interactive drawing measurement and symbol detection.

These extend the existing Project models to support the visual takeoff workflow:
- Rooms drawn on the plan with polygon boundaries  
- Symbol detections (from AI or manual) linked to rooms and products
- Cable run measurements between points
- Floor area measurements

ADD TO: app/models/takeoff.py (new file)
THEN ADD to app/models/__init__.py:
    from app.models.takeoff import TakeoffRoom, TakeoffSymbolDetection, TakeoffCableRun, TakeoffArea
"""
from app.extensions import db
from datetime import datetime
from sqlalchemy import Index
import json


class TakeoffRoom(db.Model):
    """A room/zone drawn on a project drawing for grouping symbols and materials"""
    __tablename__ = 'takeoff_room'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False, index=True)

    # Room details
    name = db.Column(db.String(100), nullable=False)  # Kitchen, Lounge, Bedroom 1, etc.
    floor_level = db.Column(db.String(50))  # ground, first, second, basement
    room_type = db.Column(db.String(50))  # kitchen, bedroom, bathroom, hallway, utility, garage, commercial

    # Polygon boundary on the drawing (stored as JSON array of {x, y} points)
    # These are pixel coordinates on the rendered drawing
    boundary_points = db.Column(db.Text)  # JSON: [{"x": 100, "y": 200}, ...]

    # Calculated area (from boundary polygon, using drawing scale)
    area_sqm = db.Column(db.Numeric(10, 2))
    area_pixels = db.Column(db.Numeric(12, 2))  # Raw pixel area before scale conversion

    # Drawing position (bounding box for quick hit-testing)
    bbox_x = db.Column(db.Integer)
    bbox_y = db.Column(db.Integer)
    bbox_w = db.Column(db.Integer)
    bbox_h = db.Column(db.Integer)

    # Display
    color = db.Column(db.String(7), default='#6366f1')  # Hex color for room overlay
    sort_order = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = db.relationship('Project', backref=db.backref('takeoff_rooms', lazy='dynamic', cascade='all, delete-orphan'))
    document = db.relationship('ProjectDocument', backref=db.backref('rooms', lazy='dynamic'))
    detections = db.relationship('TakeoffSymbolDetection', backref='room', lazy='dynamic', cascade='all, delete-orphan')

    def get_boundary_points(self):
        """Parse boundary points from JSON"""
        if self.boundary_points:
            try:
                return json.loads(self.boundary_points)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def set_boundary_points(self, points):
        """Store boundary points as JSON"""
        self.boundary_points = json.dumps(points)

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'name': self.name,
            'floor_level': self.floor_level,
            'room_type': self.room_type,
            'boundary_points': self.get_boundary_points(),
            'area_sqm': float(self.area_sqm) if self.area_sqm else None,
            'bbox': {'x': self.bbox_x, 'y': self.bbox_y, 'w': self.bbox_w, 'h': self.bbox_h},
            'color': self.color,
            'sort_order': self.sort_order,
            'detections_count': self.detections.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TakeoffSymbolDetection(db.Model):
    """A detected or manually placed symbol on a drawing, linked to a room and product.
    
    Flow: 
    1. User draws box over symbol in key area -> creates a SymbolTemplate  
    2. AI/OpenCV scans drawing and finds matches -> creates TakeoffSymbolDetection per match
    3. User links a product (from QB/Xero) to the symbol type
    4. Detections get converted to ProjectMaterial line items
    """
    __tablename__ = 'takeoff_symbol_detection'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'), nullable=True, index=True)

    # Symbol type (links detections of the same symbol together)
    symbol_type_id = db.Column(db.String(50), nullable=False, index=True)  # e.g. "sym_ds", "sym_dl"
    symbol_label = db.Column(db.String(100))  # e.g. "Double Socket", "Downlight"

    # Position on drawing (pixel coordinates)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)

    # Detection confidence (0-1, 1 = manual/confirmed, <1 = AI detected)
    confidence = db.Column(db.Numeric(4, 3), default=1.0)
    confirmed = db.Column(db.Boolean, default=False)  # User confirmed this detection
    rejected = db.Column(db.Boolean, default=False)  # User rejected this detection

    # Linked product (from QB/Xero)
    material_id = db.Column(db.Integer, db.ForeignKey('project_material.id'), nullable=True)
    part_number = db.Column(db.String(100))
    product_description = db.Column(db.String(255))

    # Source
    source = db.Column(db.String(20), default='ai')  # ai, manual, opencv

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    project = db.relationship('Project', backref=db.backref('symbol_detections', lazy='dynamic'))
    document = db.relationship('ProjectDocument', backref=db.backref('detections', lazy='dynamic'))
    material = db.relationship('ProjectMaterial', backref=db.backref('detections', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else None,
            'symbol_type_id': self.symbol_type_id,
            'symbol_label': self.symbol_label,
            'x': self.x,
            'y': self.y,
            'confidence': float(self.confidence) if self.confidence else None,
            'confirmed': self.confirmed,
            'rejected': self.rejected,
            'part_number': self.part_number,
            'product_description': self.product_description,
            'material_id': self.material_id,
            'source': self.source,
        }


class TakeoffSymbolTemplate(db.Model):
    """A symbol template created when user draws a box over a key symbol.
    
    Stores the cropped reference image for AI matching and the product linkage
    so future detections of the same symbol auto-link to the product.
    """
    __tablename__ = 'takeoff_symbol_template'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)

    # Symbol identity
    symbol_type_id = db.Column(db.String(50), nullable=False)  # Generated ID e.g. "sym_abc123"
    label = db.Column(db.String(100), nullable=False)  # User-provided label e.g. "Double Socket"

    # Cropped reference image from the key area
    crop_x = db.Column(db.Integer)  # Bounding box on original drawing
    crop_y = db.Column(db.Integer)
    crop_w = db.Column(db.Integer)
    crop_h = db.Column(db.Integer)
    crop_image_path = db.Column(db.String(500))  # Saved cropped image file

    # Linked product (default for all detections of this symbol)
    default_part_number = db.Column(db.String(100))
    default_product_description = db.Column(db.String(255))
    default_unit_cost = db.Column(db.Numeric(10, 4))
    default_unit_sell = db.Column(db.Numeric(10, 4))
    qb_item_id = db.Column(db.String(50))

    # Detection stats
    total_found = db.Column(db.Integer, default=0)
    confirmed_count = db.Column(db.Integer, default=0)

    # Display
    color = db.Column(db.String(7), default='#3b82f6')
    icon = db.Column(db.String(10))  # Emoji or character for display

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    project = db.relationship('Project', backref=db.backref('symbol_templates', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'symbol_type_id': self.symbol_type_id,
            'label': self.label,
            'crop': {'x': self.crop_x, 'y': self.crop_y, 'w': self.crop_w, 'h': self.crop_h},
            'default_part_number': self.default_part_number,
            'default_product_description': self.default_product_description,
            'default_unit_cost': float(self.default_unit_cost) if self.default_unit_cost else None,
            'default_unit_sell': float(self.default_unit_sell) if self.default_unit_sell else None,
            'qb_item_id': self.qb_item_id,
            'total_found': self.total_found,
            'confirmed_count': self.confirmed_count,
            'color': self.color,
            'icon': self.icon,
        }


class TakeoffCableRun(db.Model):
    """A cable run measurement - click-to-click path on the drawing"""
    __tablename__ = 'takeoff_cable_run'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'), nullable=True)

    # Cable type
    cable_type = db.Column(db.String(50), nullable=False)  # lighting, socket, cooker, shower, data, fire_alarm, swa
    cable_label = db.Column(db.String(100))  # e.g. "1.5mm T&E", "2.5mm T&E", "6.0mm T&E"

    # Route points on drawing (JSON array of {x, y})
    route_points = db.Column(db.Text, nullable=False)  # JSON: [{"x": 100, "y": 200}, ...]

    # Measurements
    length_pixels = db.Column(db.Numeric(12, 2))
    length_metres = db.Column(db.Numeric(10, 2))
    waste_percent = db.Column(db.Numeric(5, 2), default=10.0)  # Default 10% waste
    total_metres = db.Column(db.Numeric(10, 2))  # length + waste

    # Linked product
    material_id = db.Column(db.Integer, db.ForeignKey('project_material.id'), nullable=True)
    part_number = db.Column(db.String(100))

    # Notes
    notes = db.Column(db.Text)  # e.g. "Kitchen ring main", "Upstairs lighting circuit"
    circuit_ref = db.Column(db.String(50))  # e.g. "C1", "C2", "RC1"

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    project = db.relationship('Project', backref=db.backref('cable_runs', lazy='dynamic', cascade='all, delete-orphan'))
    document = db.relationship('ProjectDocument', backref=db.backref('cable_runs', lazy='dynamic'))
    room = db.relationship('TakeoffRoom', backref=db.backref('cable_runs', lazy='dynamic'))
    material = db.relationship('ProjectMaterial', backref=db.backref('cable_runs', lazy='dynamic'))

    def get_route_points(self):
        if self.route_points:
            try:
                return json.loads(self.route_points)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def set_route_points(self, points):
        self.route_points = json.dumps(points)

    def calculate_length(self, scale_px_per_metre):
        """Calculate cable length from route points and drawing scale"""
        points = self.get_route_points()
        if len(points) < 2:
            self.length_pixels = 0
            self.length_metres = 0
            self.total_metres = 0
            return

        total_px = 0
        for i in range(1, len(points)):
            dx = points[i]['x'] - points[i-1]['x']
            dy = points[i]['y'] - points[i-1]['y']
            total_px += (dx**2 + dy**2) ** 0.5

        self.length_pixels = round(total_px, 2)
        self.length_metres = round(total_px / scale_px_per_metre, 2) if scale_px_per_metre > 0 else 0
        waste = float(self.waste_percent or 10) / 100
        self.total_metres = round(float(self.length_metres) * (1 + waste), 2)

    def to_dict(self):
        return {
            'id': self.id,
            'room_id': self.room_id,
            'room_name': self.room.name if self.room else None,
            'cable_type': self.cable_type,
            'cable_label': self.cable_label,
            'route_points': self.get_route_points(),
            'length_metres': float(self.length_metres) if self.length_metres else 0,
            'waste_percent': float(self.waste_percent) if self.waste_percent else 10,
            'total_metres': float(self.total_metres) if self.total_metres else 0,
            'part_number': self.part_number,
            'material_id': self.material_id,
            'notes': self.notes,
            'circuit_ref': self.circuit_ref,
        }


class TakeoffArea(db.Model):
    """A measured floor area on the drawing"""
    __tablename__ = 'takeoff_area'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'), nullable=True)

    # Label
    label = db.Column(db.String(100))

    # Polygon points (JSON)
    points = db.Column(db.Text, nullable=False)

    # Calculated area
    area_pixels = db.Column(db.Numeric(12, 2))
    area_sqm = db.Column(db.Numeric(10, 2))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    project = db.relationship('Project', backref=db.backref('takeoff_areas', lazy='dynamic', cascade='all, delete-orphan'))
    room = db.relationship('TakeoffRoom', backref=db.backref('areas', lazy='dynamic'))

    def get_points(self):
        if self.points:
            try:
                return json.loads(self.points)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def set_points(self, pts):
        self.points = json.dumps(pts)

    def calculate_area(self, scale_px_per_metre):
        """Calculate area using shoelace formula"""
        pts = self.get_points()
        if len(pts) < 3:
            self.area_pixels = 0
            self.area_sqm = 0
            return

        # Shoelace formula
        n = len(pts)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += pts[i]['x'] * pts[j]['y']
            area -= pts[j]['x'] * pts[i]['y']
        area = abs(area) / 2

        self.area_pixels = round(area, 2)
        if scale_px_per_metre > 0:
            self.area_sqm = round(area / (scale_px_per_metre ** 2), 2)
        else:
            self.area_sqm = 0

    def to_dict(self):
        return {
            'id': self.id,
            'room_id': self.room_id,
            'label': self.label,
            'points': self.get_points(),
            'area_sqm': float(self.area_sqm) if self.area_sqm else 0,
        }


# Indexes
Index('idx_detection_project_symbol', TakeoffSymbolDetection.project_id, TakeoffSymbolDetection.symbol_type_id)
Index('idx_detection_room', TakeoffSymbolDetection.room_id)
Index('idx_cable_project', TakeoffCableRun.project_id)
Index('idx_room_project', TakeoffRoom.project_id)
