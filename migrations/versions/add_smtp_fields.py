"""Add SMTP fields to email_connection

Revision ID: add_smtp_fields
Revises: add_line_sort_order
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_smtp_fields'
down_revision = 'add_line_sort_order'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('email_connection', schema=None) as batch_op:
        batch_op.add_column(sa.Column('smtp_server', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column('smtp_port', sa.Integer(), nullable=True, server_default='587'))
        batch_op.add_column(sa.Column('smtp_use_tls', sa.Boolean(), nullable=True, server_default='true'))


def downgrade():
    with op.batch_alter_table('email_connection', schema=None) as batch_op:
        batch_op.drop_column('smtp_use_tls')
        batch_op.drop_column('smtp_port')
        batch_op.drop_column('smtp_server')
