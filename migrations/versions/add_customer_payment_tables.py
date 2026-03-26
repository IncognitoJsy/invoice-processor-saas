"""Add customer payment tables

Revision ID: add_customer_payment_tables
Revises: add_customer_quote_tables
Create Date: 2026-03-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_customer_payment_tables'
down_revision = 'add_customer_quote_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_payment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('payment_method', sa.String(50), server_default='bank_transfer'),
        sa.Column('reference', sa.String(255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_payment_user_id', 'customer_payment', ['user_id'])

    op.create_table('customer_invoice_payment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payment_id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.Integer(), nullable=False),
        sa.Column('amount_applied', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['payment_id'], ['customer_payment.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['customer_invoice.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('customer_invoice_payment')
    op.drop_table('customer_payment')
