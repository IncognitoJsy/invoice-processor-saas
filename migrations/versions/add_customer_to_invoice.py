"""Add customer_id and job_id to invoice table

Revision ID: add_customer_to_invoice
Revises: add_full_platform_tables
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_customer_to_invoice'
down_revision = 'add_full_platform_tables'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_customer_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('platform_job_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('customer_match_confidence', sa.String(20), nullable=True))


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('customer_match_confidence')
        batch_op.drop_column('platform_job_id')
        batch_op.drop_column('platform_customer_id')
