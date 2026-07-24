"""Sync-mode customer link: nullable external_id + source on customer (+ unique index).

Lets a sync-mode job materialise a local Customer row for a picked QuickBooks/Xero customer, keyed on
the SAME id the sync/customer_cache use (QB Customer.Id / Xero ContactID) — so find-or-create is
stable across a rename and never duplicates (incl. Parent:Child sub-customers).

Additive only — NO drops, NO type changes, NO data mutation:
  * ALTER customer: add 2 NULLABLE columns (external_id, source). Nullable ⇒ no backfill, safe on
    populated tables on every env incl. Postgres-ot-n. Existing full-suite customers stay NULL/NULL.
  * CREATE UNIQUE INDEX (user_id, source, external_id): NULLs are distinct in Postgres, so the many
    NULL/NULL full-suite rows never collide — the constraint only binds materialised sync customers.

Model authored in lockstep (app/models/customer.py); verified drift-free via flask schema-check.

Revision ID: add_customer_external_link
Revises: add_job_metadata_snapshot
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_customer_external_link'
down_revision = 'add_job_metadata_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('customer') as batch_op:
        batch_op.add_column(sa.Column('external_id', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('source', sa.String(length=20), nullable=True))
    op.create_index('uq_customer_user_source_ext', 'customer',
                    ['user_id', 'source', 'external_id'], unique=True)


def downgrade():
    op.drop_index('uq_customer_user_source_ext', table_name='customer')
    with op.batch_alter_table('customer') as batch_op:
        batch_op.drop_column('source')
        batch_op.drop_column('external_id')
