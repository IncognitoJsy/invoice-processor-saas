"""Add full platform tables - customers, jobs, products, documents

Revision ID: add_full_platform_tables
Revises: add_multi_trade_fields
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_full_platform_tables'
down_revision = 'add_multi_trade_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('company_name', sa.String(255), nullable=True),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('address_line1', sa.String(255), nullable=True),
        sa.Column('address_line2', sa.String(255), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('postcode', sa.String(20), nullable=True),
        sa.Column('country', sa.String(50), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_user_id', 'customer', ['user_id'])

    op.create_table('job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id'), nullable=True),
        sa.Column('job_number', sa.String(50), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=True, server_default='quoted'),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_job_user_id', 'job', ['user_id'])

    op.create_table('product_service',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('sku', sa.String(100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('item_type', sa.String(20), nullable=True, server_default='product'),
        sa.Column('purchase_price', sa.Float(), nullable=True, server_default='0'),
        sa.Column('sale_price', sa.Float(), nullable=True, server_default='0'),
        sa.Column('unit_of_measure', sa.String(50), nullable=True),
        sa.Column('tax_applicable', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('track_stock', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('quantity_in_stock', sa.Float(), nullable=True, server_default='0'),
        sa.Column('low_stock_threshold', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_product_service_user_id', 'product_service', ['user_id'])

    op.create_table('customer_document',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id'), nullable=True),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('job.id'), nullable=True),
        sa.Column('doc_type', sa.String(50), nullable=True),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('storage_path', sa.String(500), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('doc_date', sa.DateTime(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_document_user_id', 'customer_document', ['user_id'])


def downgrade():
    op.drop_table('customer_document')
    op.drop_table('product_service')
    op.drop_table('job')
    op.drop_table('customer')
