"""Add customer quote tables

Revision ID: add_customer_quote_tables
Revises: logo_url_to_text
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_customer_quote_tables'
down_revision = 'logo_url_to_text'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_quote',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=True),
        sa.Column('quote_number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('subtotal', sa.Float(), server_default='0'),
        sa.Column('tax_rate', sa.Float(), server_default='0'),
        sa.Column('tax_amount', sa.Float(), server_default='0'),
        sa.Column('total', sa.Float(), server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('payment_terms', sa.String(20), server_default='30'),
        sa.Column('acceptance_token', sa.String(64), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_by_name', sa.String(255), nullable=True),
        sa.Column('converted_invoice_id', sa.Integer(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id']),
        sa.ForeignKeyConstraint(['converted_invoice_id'], ['customer_invoice.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_quote_user_id', 'customer_quote', ['user_id'])
    op.create_index('ix_customer_quote_acceptance_token', 'customer_quote', ['acceptance_token'], unique=True)

    op.create_table('customer_quote_line',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Float(), server_default='1'),
        sa.Column('unit_price', sa.Float(), server_default='0'),
        sa.Column('line_total', sa.Float(), server_default='0'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.ForeignKeyConstraint(['quote_id'], ['customer_quote.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('customer_quote_line')
    op.drop_table('customer_quote')
