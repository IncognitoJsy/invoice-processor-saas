"""Add invoice_template to user

Revision ID: add_invoice_template
Revises: add_smtp_fields
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_invoice_template'
down_revision = 'add_smtp_fields'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('invoice_template', sa.String(20),
                                      nullable=True, server_default='classic'))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('invoice_template')
