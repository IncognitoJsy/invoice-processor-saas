"""Add job cards

Revision ID: add_job_cards
Revises: add_invoice_view_tracking
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_job_cards'
down_revision = 'add_invoice_view_tracking'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('job_card',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), default='new'),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('quote_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['quote_id'], ['customer_quote.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_job_card_user_id', 'job_card', ['user_id'])
    op.create_index('ix_job_card_customer_id', 'job_card', ['customer_id'])

    # Link supplier invoices to job cards
    op.add_column('invoice', sa.Column('job_card_id', sa.Integer(), nullable=True))

    # Link customer invoices to job cards
    op.add_column('customer_invoice', sa.Column('job_card_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('customer_invoice', 'job_card_id')
    op.drop_column('invoice', 'job_card_id')
    op.drop_index('ix_job_card_customer_id', 'job_card')
    op.drop_index('ix_job_card_user_id', 'job_card')
    op.drop_table('job_card')
