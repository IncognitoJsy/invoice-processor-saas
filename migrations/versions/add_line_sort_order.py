"""Add sort_order to customer_invoice_line

Revision ID: add_line_sort_order
Revises: add_logo_and_colour
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_line_sort_order'
down_revision = 'add_logo_and_colour'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customer_invoice_line', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'))


def downgrade():
    with op.batch_alter_table('customer_invoice_line', schema=None) as batch_op:
        batch_op.drop_column('sort_order')
