"""Add manual-override flag + created/updated stamps to invoice_item

Additive, low-risk (same class as add_output_tax_code_picker):
  - price_overridden BOOLEAN NOT NULL DEFAULT false — the manual per-unit price flag (drives the
    "manual" markup badge AND the override; one shared state). A manual price bypasses the auto
    retail cap; any future re-price action MUST skip price_overridden rows.
  - created_at / updated_at DATETIME — per-line stamps (feature 4).

Revision ID: add_invoice_item_override_stamps
Revises: add_output_tax_code_picker
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_invoice_item_override_stamps'
down_revision = 'add_output_tax_code_picker'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('invoice_item', sa.Column('price_overridden', sa.Boolean(), nullable=False,
                                            server_default=sa.false()))
    op.add_column('invoice_item', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('invoice_item', sa.Column('updated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('invoice_item', 'updated_at')
    op.drop_column('invoice_item', 'created_at')
    op.drop_column('invoice_item', 'price_overridden')
