"""Merge fix_queue_fk and add_imap_fields heads

Revision ID: merge_heads_001
Revises: fix_queue_fk, add_imap_fields
Create Date: 2026-02-16
"""
from alembic import op

revision = 'merge_heads_001'
down_revision = ('fix_queue_fk', 'add_imap_fields')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
