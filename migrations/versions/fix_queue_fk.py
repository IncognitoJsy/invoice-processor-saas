"""Fix queued_invoice foreign key to SET NULL on delete

Revision ID: fix_queue_fk
Revises: add_queue_tables
Create Date: 2026-02-12
"""
from alembic import op

revision = 'fix_queue_fk'
down_revision = 'add_queue_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the old constraint and recreate with ON DELETE SET NULL
    # PostgreSQL syntax
    op.drop_constraint('queued_invoice_processed_invoice_id_fkey', 'queued_invoice', type_='foreignkey')
    op.create_foreign_key(
        'queued_invoice_processed_invoice_id_fkey',
        'queued_invoice', 'invoice',
        ['processed_invoice_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('queued_invoice_processed_invoice_id_fkey', 'queued_invoice', type_='foreignkey')
    op.create_foreign_key(
        'queued_invoice_processed_invoice_id_fkey',
        'queued_invoice', 'invoice',
        ['processed_invoice_id'], ['id']
    )
