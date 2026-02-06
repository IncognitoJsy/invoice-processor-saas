"""
GoZappify Takeoff Models - Compatible with existing database
"""

from app.extensions import db
from datetime import datetime
import json


class TakeoffRoom(db.Model):
    """Room/zone on a drawing for grouping items."""
    __tablename__ = 'takeoff_room'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'))
    name = db.Column(db.String(100), nullable=False)
    floor_level = db.Column(db.String(50))
    room_type = db.Column(db.String(50))
    color = db.Column(db.String(20), default='#6366f1')
    sort_order = db.Column(db.Integer, default=0)
    
    # Boundary
    boundary_points = db.Column(db.Text)  # JSON string
    bbox_x = db.Column(db.Integer)
    bbox_y = db.Column(db.Integer)
    bbox_w = db.Column(db.Integer)
    bbox_h = db.Column(db.Integer)
    
    # Area
    area_pixels = db.Column(db.Float)
    area_sqm = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    detections = db.relationship('TakeoffSymbolDetection', backref='room', lazy='dynamic')
    cable_runs = db.relationship('TakeoffCableRun', backref='room', lazy='dynamic')
    
    def get_boundary_points(self):
        if self.boundary_points:
            try:
                return json.loads(self.boundary_points)
            except:
                return []
        return []
    
    def set_boundary_points(self, points):
        self.boundary_points = json.dumps(points) if points else None
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'name': self.name,
            'floor_level': self.floor_level,
            'room_type': self.room_type,
            'color': self.color,
            'sort_order': self.sort_order,
            'boundary_points': self.get_boundary_points(),
            'bbox': {'x': self.bbox_x, 'y': self.bbox_y, 'w': self.bbox_w, 'h': self.bbox_h},
            'area_pixels': self.area_pixels,
            'area_sqm': self.area_sqm,
        }


class TakeoffSymbolTemplate(db.Model):
    """Template for a symbol to detect."""
    __tablename__ = 'takeoff_symbol_template'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'))
    
    symbol_type_id = db.Column(db.String(50))
    label = db.Column(db.String(200))
    color = db.Column(db.String(20), default='#3b82f6')
    icon = db.Column(db.String(50))
    
    # Crop region
    crop_x = db.Column(db.Integer)
    crop_y = db.Column(db.Integer)
    crop_w = db.Column(db.Integer)
    crop_h = db.Column(db.Integer)
    crop_image_path = db.Column(db.String(500))
    
    # Product linking
    default_part_number = db.Column(db.String(100))
    default_product_description = db.Column(db.String(500))
    default_unit_cost = db.Column(db.Numeric(10, 2))
    default_unit_sell = db.Column(db.Numeric(10, 2))
    qb_item_id = db.Column(db.String(50))
    
    # Stats
    total_found = db.Column(db.Integer, default=0)
    confirmed_count = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    detections = db.relationship('TakeoffSymbolDetection', backref='template', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'symbol_type_id': self.symbol_type_id,
            'label': self.label,
            'color': self.color,
            'icon': self.icon,
            'crop': {'x': self.crop_x, 'y': self.crop_y, 'w': self.crop_w, 'h': self.crop_h},
            'crop_image_path': self.crop_image_path,
            'default_part_number': self.default_part_number,
            'default_product_description': self.default_product_description,
            'default_unit_cost': float(self.default_unit_cost) if self.default_unit_cost else None,
            'default_unit_sell': float(self.default_unit_sell) if self.default_unit_sell else None,
            'total_found': self.total_found,
            'confirmed_count': self.confirmed_count,
        }


class TakeoffSymbolDetection(db.Model):
    """A detected instance of a symbol."""
    __tablename__ = 'takeoff_symbol_detection'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    
    
    symbol_type_id = db.Column(db.String(50))
    symbol_label = db.Column(db.String(200))
    
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    
    confidence = db.Column(db.Numeric(4, 3), default=0)
    confirmed = db.Column(db.Boolean, default=False)
    rejected = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(20), default='opencv')
    
    part_number = db.Column(db.String(100))
    product_description = db.Column(db.String(500))
    material_id = db.Column(db.Integer, db.ForeignKey('project_material.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'room_id': self.room_id,
            'symbol_type_id': self.symbol_type_id,
            'symbol_label': self.symbol_label,
            'x': self.x,
            'y': self.y,
            'confidence': float(self.confidence) if self.confidence else 0,
            'confirmed': self.confirmed,
            'rejected': self.rejected,
            'source': self.source,
            'part_number': self.part_number,
            'product_description': self.product_description,
        }


class TakeoffCableRun(db.Model):
    """A measured cable run."""
    __tablename__ = 'takeoff_cable_run'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    
    cable_type = db.Column(db.String(50), nullable=False)
    cable_label = db.Column(db.String(100))
    
    route_points = db.Column(db.Text)  # JSON
    length_pixels = db.Column(db.Float)
    length_metres = db.Column(db.Numeric(10, 2))
    waste_percent = db.Column(db.Integer, default=10)
    total_metres = db.Column(db.Numeric(10, 2))
    
    circuit_ref = db.Column(db.String(50))
    notes = db.Column(db.Text)
    part_number = db.Column(db.String(100))
    material_id = db.Column(db.Integer, db.ForeignKey('project_material.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_route_points(self):
        if self.route_points:
            try:
                return json.loads(self.route_points)
            except:
                return []
        return []
    
    def set_route_points(self, points):
        self.route_points = json.dumps(points) if points else None
    
    def calculate_length(self, px_per_metre=50):
        points = self.get_route_points()
        if len(points) < 2:
            return
        total_px = 0
        for i in range(len(points) - 1):
            dx = points[i+1]['x'] - points[i]['x']
            dy = points[i+1]['y'] - points[i]['y']
            total_px += (dx**2 + dy**2) ** 0.5
        self.length_pixels = total_px
        self.length_metres = round(total_px / px_per_metre, 2)
        waste = 1 + (self.waste_percent or 10) / 100
        self.total_metres = round(float(self.length_metres) * waste, 2)
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'room_id': self.room_id,
            'cable_type': self.cable_type,
            'cable_label': self.cable_label,
            'route_points': self.get_route_points(),
            'length_pixels': self.length_pixels,
            'length_metres': float(self.length_metres) if self.length_metres else None,
            'waste_percent': self.waste_percent,
            'total_metres': float(self.total_metres) if self.total_metres else None,
            'circuit_ref': self.circuit_ref,
            'part_number': self.part_number,
        }


class TakeoffArea(db.Model):
    """A measured area."""
    __tablename__ = 'takeoff_area'
    
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('project_document.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('takeoff_room.id'))
    
    label = db.Column(db.String(100))
    points = db.Column(db.Text)  # JSON
    area_pixels = db.Column(db.Float)
    area_sqm = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def get_points(self):
        if self.points:
            try:
                return json.loads(self.points)
            except:
                return []
        return []
    
    def set_points(self, points):
        self.points = json.dumps(points) if points else None
    
    def calculate_area(self, px_per_metre=50):
        points = self.get_points()
        if len(points) < 3:
            return
        # Shoelace formula
        n = len(points)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += points[i]['x'] * points[j]['y']
            area -= points[j]['x'] * points[i]['y']
        self.area_pixels = abs(area) / 2
        self.area_sqm = round(self.area_pixels / (px_per_metre ** 2), 2)
    
    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'document_id': self.document_id,
            'room_id': self.room_id,
            'label': self.label,
            'points': self.get_points(),
            'area_pixels': self.area_pixels,
            'area_sqm': self.area_sqm,
        }
