"""Add customer_cache table (per-user QBO/Xero customer cache)

Creates ONE new table so the invoice-sync customer picker is served from a local cache
instead of pulling ~1300 customers live from QuickBooks/Xero on every modal open.

Safe on all envs incl Postgres-ot-n:
  * A brand-new table has ZERO existing rows on every env, so there is NO
    NOT-NULL-on-populated-rows backfill trap (the reconcile_d lesson applies to column
    ADDS on populated tables — this is not that).
  * Idempotent / env-drift safe: guarded by inspector so re-running, or an env that already
    has the table, is a no-op.
  * Touches no existing table or data.

Revision ID: add_customer_cache
Revises: add_invoice_item_excluded
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_customer_cache'
down_revision = 'add_invoice_item_excluded'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'customer_cache' not in insp.get_table_names():
        op.create_table(
            'customer_cache',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('external_id', sa.String(length=200), nullable=False),        # QB Customer.Id / Xero ContactID
            sa.Column('display_name', sa.String(length=255), nullable=False),
            sa.Column('fully_qualified_name', sa.String(length=255), nullable=True),  # QB Parent:Child; null for Xero
            sa.Column('company_name', sa.String(length=255), nullable=True),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('source', sa.String(length=20), nullable=False),               # 'quickbooks' | 'xero'
            # server_default so any insert is safe even if the app omitted it; app sets it per refresh.
            sa.Column('synced_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(['user_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    # Indexes — each guarded independently in case a prior partial run left the table without them.
    existing = set()
    if 'customer_cache' in insp.get_table_names():
        existing = {ix['name'] for ix in insp.get_indexes('customer_cache')}
    if 'uq_customer_cache_user_source_ext' not in existing:
        op.create_index('uq_customer_cache_user_source_ext', 'customer_cache',
                        ['user_id', 'source', 'external_id'], unique=True)
    if 'ix_customer_cache_user_name' not in existing:
        op.create_index('ix_customer_cache_user_name', 'customer_cache',
                        ['user_id', 'display_name'], unique=False)
    if 'ix_customer_cache_user_id' not in existing:
        op.create_index('ix_customer_cache_user_id', 'customer_cache', ['user_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'customer_cache' in insp.get_table_names():
        op.drop_table('customer_cache')   # drops its indexes with it
