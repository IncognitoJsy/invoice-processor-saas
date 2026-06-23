"""Reconcile B — invoice_item money precision -> NUMERIC(10,4) + part_number -> VARCHAR(255) (risk #10)

Single idempotent ALTER (one table rewrite) under a short lock_timeout. Prod money columns are
NUMERIC(10,2) -> widened to (10,4) to match the model (cost_per_item carries the 305m bulk-cable
per-metre 4dp rate); part_number is already 255 on prod (no-op there), widened on staging.
Measured on prod: 971 rows / 168 kB, rewrite ~1 ms.

Revision ID: reconcile_b_invoice_item_precision
Revises: reconcile_a_orphan_columns
"""
from alembic import op
import sqlalchemy as sa

revision = 'reconcile_b_item_precision'  # <=32 chars: alembic_version.version_num is VARCHAR(32)
down_revision = 'reconcile_a_orphan_columns'
branch_labels = None
depends_on = None

_NUMERIC_COLS = ('cost_per_item', 'original_unit_price', 'selling_price', 'profit_per_item')


def _coltypes(table):
    return {c['name']: str(c['type']) for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return  # SQLite (tests) builds these from the model already
    op.execute("SET lock_timeout = '5s'")
    types = _coltypes('invoice_item')
    clauses = []
    for col in _NUMERIC_COLS:
        if col in types and types[col] != 'NUMERIC(10, 4)':
            clauses.append(f'ALTER COLUMN {col} TYPE numeric(10,4)')
    if types.get('part_number') not in (None, 'VARCHAR(255)'):
        clauses.append('ALTER COLUMN part_number TYPE varchar(255)')
    if clauses:
        op.execute('ALTER TABLE invoice_item ' + ', '.join(clauses))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("SET lock_timeout = '5s'")
    types = _coltypes('invoice_item')
    clauses = []
    for col in _NUMERIC_COLS:
        if col in types and types[col] != 'NUMERIC(10, 2)':
            clauses.append(f'ALTER COLUMN {col} TYPE numeric(10,2)')
    if types.get('part_number') not in (None, 'VARCHAR(100)'):
        clauses.append('ALTER COLUMN part_number TYPE varchar(100)')
    if clauses:
        op.execute('ALTER TABLE invoice_item ' + ', '.join(clauses))
