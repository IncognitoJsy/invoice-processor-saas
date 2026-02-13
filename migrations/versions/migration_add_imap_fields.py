"""
Database Migration: Add IMAP fields to email_connection table
=============================================================
Add this as a new Alembic migration file.

Run: flask db revision -m "add imap fields to email connection"
Then replace the content with this, updating the revision IDs.

Or manually add to: migrations/versions/add_imap_fields.py
"""

"""add imap fields to email connection

Revision ID: UPDATE_THIS
Revises: UPDATE_THIS_TO_YOUR_LATEST
Create Date: 2026-02-13
"""
from alembic import op
import sqlalchemy as sa

# IMPORTANT: Update these to match your migration chain
# Run 'flask db heads' to find your current latest revision
revision = 'add_imap_fields'
down_revision = 'add_queue_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Add IMAP-specific columns to email_connection table
    with op.batch_alter_table('email_connection') as batch_op:
        batch_op.add_column(sa.Column('imap_server', sa.String(255), nullable=True))
        batch_op.add_column(sa.Column('imap_port', sa.Integer(), nullable=True, default=993))
        batch_op.add_column(sa.Column('use_ssl', sa.Boolean(), nullable=True, default=True))


def downgrade():
    with op.batch_alter_table('email_connection') as batch_op:
        batch_op.drop_column('use_ssl')
        batch_op.drop_column('imap_port')
        batch_op.drop_column('imap_server')
