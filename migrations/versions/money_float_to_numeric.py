"""Migrate money columns from Float to Numeric (AUDIT risk #4, Phase 1)

Storage-only and behaviour-preserving: existing binary-float values are cast to
fixed-scale NUMERIC. This changes column TYPES only — it does NOT touch any
calculation code (that is Phase 2: the shared Decimal money() helper + tests).

Scales (matching the existing Numeric conventions in the codebase, with the
electrician-specific sub-penny choices confirmed by the founder):
  - prices (unit_price, catalogue purchase/sale price)  -> Numeric(10, 4)
  - quantities (line qty, stock levels)                 -> Numeric(10, 3)
  - line amounts + supplier-invoice tax amounts         -> Numeric(10, 2)
  - document totals / payment amounts                   -> Numeric(12, 2)
  - rates / markup percentages                          -> Numeric(5, 2)

On PostgreSQL the cast `col::numeric` plus the target scale rounds each value
deterministically (round half away from zero). On SQLite, batch mode recreates
the table and the cast is a no-op (SQLite has numeric affinity, not strict
types). Tests build the schema from the models via create_all(), so they do not
exercise this migration; it runs only against PostgreSQL (staging/production).

Revision ID: money_float_to_numeric
Revises: add_job_cards
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'money_float_to_numeric'
down_revision = 'add_job_cards'
branch_labels = None
depends_on = None


# table -> list of (column, target Numeric type)
MONEY_COLUMNS = {
    'invoice': [
        ('supplier_tax_amount', sa.Numeric(10, 2)),
        ('supplier_tax_rate', sa.Numeric(5, 2)),
        ('total_ex_tax', sa.Numeric(10, 2)),
        ('total_inc_tax', sa.Numeric(10, 2)),
    ],
    'customer_invoice': [
        ('subtotal', sa.Numeric(12, 2)),
        ('tax_rate', sa.Numeric(5, 2)),
        ('tax_amount', sa.Numeric(12, 2)),
        ('total', sa.Numeric(12, 2)),
    ],
    'customer_invoice_line': [
        ('quantity', sa.Numeric(10, 3)),
        ('unit_price', sa.Numeric(10, 4)),
        ('line_total', sa.Numeric(10, 2)),
    ],
    'customer_quote': [
        ('subtotal', sa.Numeric(12, 2)),
        ('tax_rate', sa.Numeric(5, 2)),
        ('tax_amount', sa.Numeric(12, 2)),
        ('total', sa.Numeric(12, 2)),
    ],
    'customer_quote_line': [
        ('quantity', sa.Numeric(10, 3)),
        ('unit_price', sa.Numeric(10, 4)),
        ('line_total', sa.Numeric(10, 2)),
    ],
    'customer_payment': [
        ('amount', sa.Numeric(12, 2)),
    ],
    'customer_invoice_payment': [
        ('amount_applied', sa.Numeric(12, 2)),
    ],
    'product_service': [
        ('purchase_price', sa.Numeric(10, 4)),
        ('sale_price', sa.Numeric(10, 4)),
        ('quantity_in_stock', sa.Numeric(10, 3)),
        ('low_stock_threshold', sa.Numeric(10, 3)),
    ],
    'user': [
        ('default_markup', sa.Numeric(5, 2)),
        ('tax_rate', sa.Numeric(5, 2)),
    ],
    'product_cache': [
        ('purchase_price', sa.Numeric(10, 4)),
        ('sale_price', sa.Numeric(10, 4)),
    ],
}


def upgrade():
    is_postgres = op.get_bind().dialect.name == 'postgresql'
    for table, columns in MONEY_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column, numeric_type in columns:
                kwargs = {}
                if is_postgres:
                    # Cast existing double precision to numeric; the target
                    # scale then rounds to the declared dp.
                    kwargs['postgresql_using'] = f'{column}::numeric'
                batch.alter_column(
                    column,
                    type_=numeric_type,
                    existing_type=sa.Float(),
                    **kwargs,
                )


def downgrade():
    is_postgres = op.get_bind().dialect.name == 'postgresql'
    for table, columns in MONEY_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column, numeric_type in columns:
                kwargs = {}
                if is_postgres:
                    kwargs['postgresql_using'] = f'{column}::double precision'
                batch.alter_column(
                    column,
                    type_=sa.Float(),
                    existing_type=numeric_type,
                    **kwargs,
                )
