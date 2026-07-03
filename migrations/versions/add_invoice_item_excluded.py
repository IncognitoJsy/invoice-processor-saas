"""Add soft-remove `excluded` flag to invoice_item

Additive, low-risk. Supports "remove a returned line / edit qty before sync": an excluded line is
KEPT for audit but dropped from the header-totals recompute and from every sync path.

  - excluded BOOLEAN NOT NULL DEFAULT false

IDEMPOTENT: added only if not already present, so it is safe on the drifted (prod) and clean
(staging) schemas alike (schema drift from db.create_all + inline ALTERs, AUDIT.md risk #10).
server_default=false is set at DDL time so the NOT NULL column backfills safely on every existing
row across all three environments — the reconcile_d NOT-NULL lesson (a plain NOT NULL add without a
server default fails on populated tables).

Revision ID: add_invoice_item_excluded
Revises: reconcile_f_converge
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_invoice_item_excluded'
down_revision = 'reconcile_f_converge'
branch_labels = None
depends_on = None


def _existing_columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('invoice_item')}


def upgrade():
    if 'excluded' not in _existing_columns():
        op.add_column('invoice_item', sa.Column('excluded', sa.Boolean(), nullable=False,
                                                server_default=sa.false()))


def downgrade():
    if 'excluded' in _existing_columns():
        op.drop_column('invoice_item', 'excluded')
