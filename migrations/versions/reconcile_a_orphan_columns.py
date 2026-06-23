"""Reconcile A — adopt orphan columns (risk #10): customer_invoice void/supply + customer_quote.job_card_id

Idempotent (add-if-absent): prod already has these (they were created outside Alembic), so this is a
no-op there; staging gains them. Brings the schema under migration control.

Revision ID: reconcile_a_orphan_columns
Revises: add_invoice_item_override_stamps
"""
from alembic import op
import sqlalchemy as sa

revision = 'reconcile_a_orphan_columns'
down_revision = 'add_invoice_item_override_stamps'
branch_labels = None
depends_on = None


def _cols(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _fk_names(table):
    return {fk.get('name') for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)}


def upgrade():
    ci = _cols('customer_invoice')
    if 'supply_date' not in ci:
        op.add_column('customer_invoice', sa.Column('supply_date', sa.Date(), nullable=True))
    if 'void_reason' not in ci:
        op.add_column('customer_invoice', sa.Column('void_reason', sa.String(length=100), nullable=True))
    if 'void_notes' not in ci:
        op.add_column('customer_invoice', sa.Column('void_notes', sa.Text(), nullable=True))
    if 'voided_at' not in ci:
        op.add_column('customer_invoice', sa.Column('voided_at', sa.DateTime(), nullable=True))

    if 'job_card_id' not in _cols('customer_quote'):
        op.add_column('customer_quote', sa.Column('job_card_id', sa.Integer(), nullable=True))
    # Match prod's FK name so prod (which already has it) stays a no-op.
    if (op.get_bind().dialect.name == 'postgresql'
            and 'customer_quote_job_card_id_fkey' not in _fk_names('customer_quote')):
        op.create_foreign_key('customer_quote_job_card_id_fkey', 'customer_quote', 'job_card',
                              ['job_card_id'], ['id'])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql' and 'customer_quote_job_card_id_fkey' in _fk_names('customer_quote'):
        op.drop_constraint('customer_quote_job_card_id_fkey', 'customer_quote', type_='foreignkey')
    for tbl, col in [('customer_quote', 'job_card_id'), ('customer_invoice', 'voided_at'),
                     ('customer_invoice', 'void_notes'), ('customer_invoice', 'void_reason'),
                     ('customer_invoice', 'supply_date')]:
        if col in _cols(tbl):
            op.drop_column(tbl, col)
