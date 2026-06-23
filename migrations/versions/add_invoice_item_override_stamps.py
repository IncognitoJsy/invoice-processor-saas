"""Add manual-override flag + created/updated stamps to invoice_item

Additive, low-risk. IDEMPOTENT: production's invoice_item already carried a created_at column
(schema drift from db.create_all + inline ALTERs, AUDIT.md risk #10) that staging did not, so a
plain add_column failed with DuplicateColumn and aborted boot. We now add each column only if it
is not already present, so the migration is safe on both the drifted (prod) and clean (staging)
schemas.

  - price_overridden BOOLEAN NOT NULL DEFAULT false — manual per-unit price flag (drives the
    "manual" markup badge AND the override; one shared state; bypasses the parse-time retail cap).
    Any future re-price action MUST skip price_overridden rows.
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


def _existing_columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('invoice_item')}


def upgrade():
    cols = _existing_columns()
    if 'price_overridden' not in cols:
        op.add_column('invoice_item', sa.Column('price_overridden', sa.Boolean(), nullable=False,
                                                server_default=sa.false()))
    if 'created_at' not in cols:
        op.add_column('invoice_item', sa.Column('created_at', sa.DateTime(), nullable=True))
    if 'updated_at' not in cols:
        op.add_column('invoice_item', sa.Column('updated_at', sa.DateTime(), nullable=True))


def downgrade():
    cols = _existing_columns()
    for col in ('updated_at', 'created_at', 'price_overridden'):
        if col in cols:
            op.drop_column('invoice_item', col)
