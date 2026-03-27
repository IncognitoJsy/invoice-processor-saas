"""Add invoice view tracking token

Revision ID: add_invoice_view_tracking
Revises: add_customer_payment_tables
Create Date: 2026-03-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_invoice_view_tracking'
down_revision = 'add_customer_payment_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer_invoice', sa.Column('view_token', sa.String(64), nullable=True, unique=True))
    op.add_column('customer_invoice', sa.Column('viewed_at', sa.DateTime(), nullable=True))
    op.add_column('customer_invoice', sa.Column('view_count', sa.Integer(), server_default='0'))
    op.add_column('customer_invoice', sa.Column('token_expires_at', sa.DateTime(), nullable=True))
    op.create_index('ix_customer_invoice_view_token', 'customer_invoice', ['view_token'])


def downgrade():
    op.drop_index('ix_customer_invoice_view_token', 'customer_invoice')
    op.drop_column('customer_invoice', 'token_expires_at')
    op.drop_column('customer_invoice', 'view_count')
    op.drop_column('customer_invoice', 'viewed_at')
    op.drop_column('customer_invoice', 'view_token')
