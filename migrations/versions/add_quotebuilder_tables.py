"""Add Quote Builder tables for projects, materials, labour

Revision ID: add_quotebuilder_tables
Revises: (your latest migration)
Create Date: 2026-02-04

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_quotebuilder_tables'
down_revision = 'c589dcee8aed'
branch_labels = None
depends_on = None


def upgrade():
    # Project table
    op.create_table('project',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('client_name', sa.String(length=255), nullable=True),
        sa.Column('client_email', sa.String(length=255), nullable=True),
        sa.Column('client_phone', sa.String(length=50), nullable=True),
        sa.Column('site_address', sa.Text(), nullable=True),
        sa.Column('supply_type', sa.String(length=20), nullable=True),
        sa.Column('building_type', sa.String(length=50), nullable=True),
        sa.Column('materials_markup_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('labour_rate_per_hour', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('contingency_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('total_materials_cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_materials_sell', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('total_labour_hours', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_labour_cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('subtotal', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('contingency_amount', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('grand_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('quote_valid_days', sa.Integer(), nullable=True),
        sa.Column('quoted_at', sa.DateTime(), nullable=True),
        sa.Column('qb_estimate_id', sa.String(length=50), nullable=True),
        sa.Column('qb_estimate_synced_at', sa.DateTime(), nullable=True),
        sa.Column('qb_customer_id', sa.String(length=50), nullable=True),
        sa.Column('qb_customer_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid')
    )
    op.create_index('idx_project_user_created', 'project', ['user_id', 'created_at'], unique=False)
    op.create_index('idx_project_user_status', 'project', ['user_id', 'status'], unique=False)
    op.create_index(op.f('ix_project_created_at'), 'project', ['created_at'], unique=False)
    op.create_index(op.f('ix_project_status'), 'project', ['status'], unique=False)
    op.create_index(op.f('ix_project_user_id'), 'project', ['user_id'], unique=False)

    # Project Document table
    op.create_table('project_document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=100), nullable=True),
        sa.Column('document_type', sa.String(length=50), nullable=True),
        sa.Column('floor_level', sa.String(length=50), nullable=True),
        sa.Column('system_type', sa.String(length=50), nullable=True),
        sa.Column('parsed', sa.Boolean(), nullable=True),
        sa.Column('parsed_at', sa.DateTime(), nullable=True),
        sa.Column('parse_error', sa.Text(), nullable=True),
        sa.Column('scale', sa.String(length=20), nullable=True),
        sa.Column('drawing_number', sa.String(length=100), nullable=True),
        sa.Column('revision', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_document_project_id'), 'project_document', ['project_id'], unique=False)

    # Project Material table
    op.create_table('project_material',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('manually_added', sa.Boolean(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('part_number', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('manufacturer', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('unit_cost', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('markup_percent', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('unit_sell', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('total_sell', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('price_source', sa.String(length=50), nullable=True),
        sa.Column('price_verified', sa.Boolean(), nullable=True),
        sa.Column('price_date', sa.DateTime(), nullable=True),
        sa.Column('qb_item_id', sa.String(length=50), nullable=True),
        sa.Column('qb_item_name', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.ForeignKeyConstraint(['source_document_id'], ['project_document.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_material_part_number', 'project_material', ['part_number'], unique=False)
    op.create_index('idx_material_project_category', 'project_material', ['project_id', 'category'], unique=False)
    op.create_index(op.f('ix_project_material_category'), 'project_material', ['category'], unique=False)
    op.create_index(op.f('ix_project_material_part_number'), 'project_material', ['part_number'], unique=False)
    op.create_index(op.f('ix_project_material_project_id'), 'project_material', ['project_id'], unique=False)

    # Project Labour table
    op.create_table('project_labour',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('task', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('hours', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('rate', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('auto_calculated', sa.Boolean(), nullable=True),
        sa.Column('calculation_basis', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_project_labour_project_id'), 'project_labour', ['project_id'], unique=False)

    # Supplier Quote Request table
    op.create_table('supplier_quote_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('supplier_name', sa.String(length=100), nullable=False),
        sa.Column('supplier_email', sa.String(length=255), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('items_count', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('response_file_path', sa.String(length=500), nullable=True),
        sa.Column('response_total', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_supplier_quote_request_project_id'), 'supplier_quote_request', ['project_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_supplier_quote_request_project_id'), table_name='supplier_quote_request')
    op.drop_table('supplier_quote_request')
    op.drop_index(op.f('ix_project_labour_project_id'), table_name='project_labour')
    op.drop_table('project_labour')
    op.drop_index(op.f('ix_project_material_project_id'), table_name='project_material')
    op.drop_index(op.f('ix_project_material_part_number'), table_name='project_material')
    op.drop_index(op.f('ix_project_material_category'), table_name='project_material')
    op.drop_index('idx_material_project_category', table_name='project_material')
    op.drop_index('idx_material_part_number', table_name='project_material')
    op.drop_table('project_material')
    op.drop_index(op.f('ix_project_document_project_id'), table_name='project_document')
    op.drop_table('project_document')
    op.drop_index(op.f('ix_project_user_id'), table_name='project')
    op.drop_index(op.f('ix_project_status'), table_name='project')
    op.drop_index(op.f('ix_project_created_at'), table_name='project')
    op.drop_index('idx_project_user_status', table_name='project')
    op.drop_index('idx_project_user_created', table_name='project')
    op.drop_table('project')
