"""Add tax fields to supplier invoice

Revision ID: add_supplier_tax_fields
Revises: add_invoice_template
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_supplier_tax_fields'
down_revision = 'add_invoice_template'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.add_column(sa.Column('supplier_tax_amount', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('supplier_tax_rate', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_ex_tax', sa.Float(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('total_inc_tax', sa.Float(), nullable=True, server_default='0'))


def downgrade():
    with op.batch_alter_table('invoice', schema=None) as batch_op:
        batch_op.drop_column('total_inc_tax')
        batch_op.drop_column('total_ex_tax')
        batch_op.drop_column('supplier_tax_rate')
        batch_op.drop_column('supplier_tax_amount')
