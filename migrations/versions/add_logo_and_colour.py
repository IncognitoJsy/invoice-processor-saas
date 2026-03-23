"""Add logo_url and invoice_colour to user

Revision ID: add_logo_and_colour
Revises: add_business_and_invoice_tables
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_logo_and_colour'
down_revision = 'add_business_and_invoice_tables'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logo_url', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('invoice_colour', sa.String(20), nullable=True, server_default='#2563eb'))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('invoice_colour')
        batch_op.drop_column('logo_url')
