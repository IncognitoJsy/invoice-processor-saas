"""Add business/bank details to user, customer invoice tables, invoice numbering

Revision ID: add_business_and_invoice_tables
Revises: add_customer_to_invoice
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_business_and_invoice_tables'
down_revision = 'add_customer_to_invoice'
branch_labels = None
depends_on = None


def upgrade():
    # Bank/business details on user
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bank_name', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('bank_account_name', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('bank_account_number', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('bank_sort_code', sa.String(20), nullable=True))
        batch_op.add_column(sa.Column('bank_iban', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('invoice_prefix', sa.String(10), nullable=True, server_default='INV'))
        batch_op.add_column(sa.Column('quote_prefix', sa.String(10), nullable=True, server_default='QUO'))
        batch_op.add_column(sa.Column('next_invoice_number', sa.Integer(), nullable=True, server_default='1'))
        batch_op.add_column(sa.Column('next_quote_number', sa.Integer(), nullable=True, server_default='1'))
        batch_op.add_column(sa.Column('default_payment_terms', sa.String(20), nullable=True, server_default='30'))
        batch_op.add_column(sa.Column('invoice_notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('default_invoice_mode', sa.String(20), nullable=True, server_default='itemised'))

    # Add payment_terms to customer table
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_terms', sa.String(20), nullable=True, server_default='30'))

    # Customer invoices (sent TO customers)
    op.create_table('customer_invoice',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id'), nullable=False),
        sa.Column('invoice_number', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=True, server_default='open'),
        sa.Column('invoice_mode', sa.String(20), nullable=True, server_default='itemised'),
        sa.Column('payment_terms', sa.String(20), nullable=True, server_default='30'),
        sa.Column('issue_date', sa.DateTime(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('subtotal', sa.Float(), nullable=True, server_default='0'),
        sa.Column('tax_rate', sa.Float(), nullable=True, server_default='0'),
        sa.Column('tax_amount', sa.Float(), nullable=True, server_default='0'),
        sa.Column('total', sa.Float(), nullable=True, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_invoice_user_id', 'customer_invoice', ['user_id'])
    op.create_index('ix_customer_invoice_customer_id', 'customer_invoice', ['customer_id'])

    # Customer invoice line items
    op.create_table('customer_invoice_line',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_invoice_id', sa.Integer(), sa.ForeignKey('customer_invoice.id'), nullable=False),
        sa.Column('product_service_id', sa.Integer(), sa.ForeignKey('product_service.id'), nullable=True),
        sa.Column('source_invoice_id', sa.Integer(), sa.ForeignKey('invoice.id'), nullable=True),
        sa.Column('description', sa.String(500), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True, server_default='1'),
        sa.Column('unit_price', sa.Float(), nullable=True, server_default='0'),
        sa.Column('line_total', sa.Float(), nullable=True, server_default='0'),
        sa.Column('line_type', sa.String(20), nullable=True, server_default='itemised'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_customer_invoice_line_invoice_id', 'customer_invoice_line', ['customer_invoice_id'])


def downgrade():
    op.drop_table('customer_invoice_line')
    op.drop_table('customer_invoice')
    with op.batch_alter_table('customer', schema=None) as batch_op:
        batch_op.drop_column('payment_terms')
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('default_invoice_mode')
        batch_op.drop_column('invoice_notes')
        batch_op.drop_column('default_payment_terms')
        batch_op.drop_column('next_quote_number')
        batch_op.drop_column('next_invoice_number')
        batch_op.drop_column('quote_prefix')
        batch_op.drop_column('invoice_prefix')
        batch_op.drop_column('bank_iban')
        batch_op.drop_column('bank_sort_code')
        batch_op.drop_column('bank_account_number')
        batch_op.drop_column('bank_account_name')
        batch_op.drop_column('bank_name')
