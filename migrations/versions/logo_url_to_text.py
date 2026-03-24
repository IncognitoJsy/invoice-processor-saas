"""Change logo_url from String to Text

Revision ID: logo_url_to_text
Revises: add_supplier_tax_fields
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'logo_url_to_text'
down_revision = 'add_supplier_tax_fields'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('logo_url', type_=sa.Text(), existing_type=sa.String(500))

def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column('logo_url', type_=sa.String(500), existing_type=sa.Text())
