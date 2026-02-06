"""Add takeoff tables for interactive drawing measurement

Revision ID: add_takeoff_tables
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_takeoff_tables'
down_revision = 'add_quotebuilder_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Takeoff Rooms
    op.create_table('takeoff_room',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('project_document.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('floor_level', sa.String(50)),
        sa.Column('room_type', sa.String(50)),
        sa.Column('boundary_points', sa.Text()),
        sa.Column('area_sqm', sa.Numeric(10, 2)),
        sa.Column('area_pixels', sa.Numeric(12, 2)),
        sa.Column('bbox_x', sa.Integer()),
        sa.Column('bbox_y', sa.Integer()),
        sa.Column('bbox_w', sa.Integer()),
        sa.Column('bbox_h', sa.Integer()),
        sa.Column('color', sa.String(7), server_default='#6366f1'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    )
    op.create_index('idx_takeoff_room_project', 'takeoff_room', ['project_id'])

    # Symbol Templates
    op.create_table('takeoff_symbol_template',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('project_document.id'), nullable=False),
        sa.Column('symbol_type_id', sa.String(50), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('crop_x', sa.Integer()),
        sa.Column('crop_y', sa.Integer()),
        sa.Column('crop_w', sa.Integer()),
        sa.Column('crop_h', sa.Integer()),
        sa.Column('crop_image_path', sa.String(500)),
        sa.Column('default_part_number', sa.String(100)),
        sa.Column('default_product_description', sa.String(255)),
        sa.Column('default_unit_cost', sa.Numeric(10, 4)),
        sa.Column('default_unit_sell', sa.Numeric(10, 4)),
        sa.Column('qb_item_id', sa.String(50)),
        sa.Column('total_found', sa.Integer(), server_default='0'),
        sa.Column('confirmed_count', sa.Integer(), server_default='0'),
        sa.Column('color', sa.String(7), server_default='#3b82f6'),
        sa.Column('icon', sa.String(10)),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('idx_symbol_template_project', 'takeoff_symbol_template', ['project_id'])

    # Symbol Detections
    op.create_table('takeoff_symbol_detection',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('project_document.id'), nullable=False),
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('takeoff_room.id'), nullable=True),
        sa.Column('symbol_type_id', sa.String(50), nullable=False),
        sa.Column('symbol_label', sa.String(100)),
        sa.Column('x', sa.Integer(), nullable=False),
        sa.Column('y', sa.Integer(), nullable=False),
        sa.Column('confidence', sa.Numeric(4, 3), server_default='1.0'),
        sa.Column('confirmed', sa.Boolean(), server_default='0'),
        sa.Column('rejected', sa.Boolean(), server_default='0'),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('project_material.id'), nullable=True),
        sa.Column('part_number', sa.String(100)),
        sa.Column('product_description', sa.String(255)),
        sa.Column('source', sa.String(20), server_default="'ai'"),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('idx_detection_project_symbol', 'takeoff_symbol_detection', ['project_id', 'symbol_type_id'])
    op.create_index('idx_detection_room', 'takeoff_symbol_detection', ['room_id'])

    # Cable Runs
    op.create_table('takeoff_cable_run',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('project_document.id'), nullable=False),
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('takeoff_room.id'), nullable=True),
        sa.Column('cable_type', sa.String(50), nullable=False),
        sa.Column('cable_label', sa.String(100)),
        sa.Column('route_points', sa.Text(), nullable=False),
        sa.Column('length_pixels', sa.Numeric(12, 2)),
        sa.Column('length_metres', sa.Numeric(10, 2)),
        sa.Column('waste_percent', sa.Numeric(5, 2), server_default='10.0'),
        sa.Column('total_metres', sa.Numeric(10, 2)),
        sa.Column('material_id', sa.Integer(), sa.ForeignKey('project_material.id'), nullable=True),
        sa.Column('part_number', sa.String(100)),
        sa.Column('notes', sa.Text()),
        sa.Column('circuit_ref', sa.String(50)),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_index('idx_cable_project', 'takeoff_cable_run', ['project_id'])

    # Floor Areas
    op.create_table('takeoff_area',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id'), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('project_document.id'), nullable=False),
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('takeoff_room.id'), nullable=True),
        sa.Column('label', sa.String(100)),
        sa.Column('points', sa.Text(), nullable=False),
        sa.Column('area_pixels', sa.Numeric(12, 2)),
        sa.Column('area_sqm', sa.Numeric(10, 2)),
        sa.Column('created_at', sa.DateTime()),
    )


def downgrade():
    op.drop_table('takeoff_area')
    op.drop_table('takeoff_cable_run')
    op.drop_table('takeoff_symbol_detection')
    op.drop_table('takeoff_symbol_template')
    op.drop_table('takeoff_room')
