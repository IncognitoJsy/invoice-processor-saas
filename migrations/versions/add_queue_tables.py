"""Add queue and email connection tables

Revision ID: add_queue_tables
Revises: 
Create Date: 2026-02-12
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_queue_tables'
down_revision = 'add_takeoff_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Queued Invoice table
    op.create_table('queued_invoice',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('page_count', sa.Integer(), default=1),
        sa.Column('source', sa.String(length=20), default='manual'),
        sa.Column('source_email', sa.String(length=255), nullable=True),
        sa.Column('supplier_name', sa.String(length=100), nullable=True),
        sa.Column('email_subject', sa.String(length=500), nullable=True),
        sa.Column('email_received_date', sa.DateTime(), nullable=True),
        sa.Column('email_message_id', sa.String(length=255), nullable=True),
        sa.Column('attachment_hash', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=20), default='queued'),
        sa.Column('target_tab', sa.String(length=20), nullable=True),
        sa.Column('processed_invoice_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['processed_invoice_id'], ['invoice.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_queued_invoice_user_status', 'queued_invoice', ['user_id', 'status'])
    op.create_index('ix_queued_invoice_dedup', 'queued_invoice', ['user_id', 'email_message_id', 'original_filename'])
    
    # Email Connection table
    op.create_table('email_connection',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('poll_interval_minutes', sa.Integer(), default=15),
        sa.Column('last_checked', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('emails_fetched_count', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Supplier Filter table
    op.create_table('supplier_filter',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('supplier_name', sa.String(length=100), nullable=False),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('supplier_filter')
    op.drop_table('email_connection')
    op.drop_index('ix_queued_invoice_dedup', table_name='queued_invoice')
    op.drop_index('ix_queued_invoice_user_status', table_name='queued_invoice')
    op.drop_table('queued_invoice')
