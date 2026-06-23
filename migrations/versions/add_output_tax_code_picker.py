"""Add picked output sales tax code columns to user (tax-code picker)

Stores the user's chosen output sales tax code, picked once (read-only) from the connected
accounting software. The QB/Xero resolver attaches output_tax_code_ref directly at sync time
(no per-sync TaxRate read), and user.tax_rate holds that code's rate captured at pick time.

All three columns are nullable — existing users keep NULL until they pick.

Revision ID: add_output_tax_code_picker
Revises: money_float_to_numeric
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_output_tax_code_picker'
down_revision = 'money_float_to_numeric'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('output_tax_code_ref', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('output_tax_code_name', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('output_tax_provider', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('user', 'output_tax_provider')
    op.drop_column('user', 'output_tax_code_name')
    op.drop_column('user', 'output_tax_code_ref')
