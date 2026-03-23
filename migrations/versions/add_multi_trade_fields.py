"""Add multi-trade, platform mode and tax fields to user

Revision ID: add_multi_trade_fields
Revises: add_vtq_jobs
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_multi_trade_fields'
down_revision = 'add_vtq_jobs'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('platform_mode', sa.String(20), nullable=True, server_default='sync'))
        batch_op.add_column(sa.Column('trade_type', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('tax_registered', sa.Boolean(), nullable=True, server_default='0'))
        batch_op.add_column(sa.Column('tax_number', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('tax_type', sa.String(10), nullable=True))
        batch_op.add_column(sa.Column('tax_rate', sa.Float(), nullable=True, server_default='0.0'))
        batch_op.add_column(sa.Column('tax_registered_from', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('tax_registered_from')
        batch_op.drop_column('tax_rate')
        batch_op.drop_column('tax_type')
        batch_op.drop_column('tax_number')
        batch_op.drop_column('tax_registered')
        batch_op.drop_column('country')
        batch_op.drop_column('trade_type')
        batch_op.drop_column('platform_mode')
