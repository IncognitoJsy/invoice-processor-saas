"""Reconcile C — Quote Builder / supplier_quote types + nullability, and widen supplier_name (risk #10)

Idempotent (alter-only-if-needed): adopts prod's actual types model-side, so on a prod snapshot the
type/nullable alters are no-ops; on staging they convert json->jsonb, float->numeric, narrow the
overspecified varchars, and add the NOT NULLs. supplier_account.supplier_name is widened 100->255 on
prod to match the model. All guarded by information_schema introspection; Postgres only.

RUN-TIME PRE-FLIGHT: before any DDL, a single pass checks for rows that would break a narrowing
varchar ALTER (data longer than the new limit) or a SET NOT NULL (NULL rows). If any exist the
migration aborts clean — NO schema change — with a message listing exactly what to backfill. The
snapshot proved safety at dump-time; this proves it at run-time, since data can change in between.
(Numeric float->numeric conversions are not over-flow-guarded here — scope is varchar/NULL per the
agreed spec; the snapshot confirmed current values fit the target precision.)

Revision ID: reconcile_c_qb_types
Revises: reconcile_b_item_precision
"""
import re
from alembic import op
import sqlalchemy as sa

revision = 'reconcile_c_qb_types'  # <=32 chars: alembic_version.version_num is VARCHAR(32)
down_revision = 'reconcile_b_item_precision'
branch_labels = None
depends_on = None

# (table, column, target DDL, reflected str to compare against, USING expr or None)
_TYPE_TARGETS = [
    ('supplier_account', 'supplier_name', 'varchar(255)', 'VARCHAR(255)', None),
    ('project_document', 'takeoff_v8_state', 'jsonb', 'JSONB', 'takeoff_v8_state::jsonb'),
    ('supplier_quote', 'parsed_items', 'jsonb', 'JSONB', 'parsed_items::jsonb'),
    ('supplier_quote_item', 'supplier_data', 'jsonb', 'JSONB', 'supplier_data::jsonb'),
    ('takeoff_area', 'area_pixels', 'numeric(12,2)', 'NUMERIC(12, 2)', 'area_pixels::numeric(12,2)'),
    ('takeoff_area', 'area_sqm', 'numeric(10,2)', 'NUMERIC(10, 2)', 'area_sqm::numeric(10,2)'),
    ('takeoff_cable_run', 'length_pixels', 'numeric(12,2)', 'NUMERIC(12, 2)', 'length_pixels::numeric(12,2)'),
    ('takeoff_cable_run', 'waste_percent', 'numeric(5,2)', 'NUMERIC(5, 2)', 'waste_percent::numeric(5,2)'),
    ('takeoff_room', 'color', 'varchar(7)', 'VARCHAR(7)', None),
    ('takeoff_room', 'area_pixels', 'numeric(12,2)', 'NUMERIC(12, 2)', 'area_pixels::numeric(12,2)'),
    ('takeoff_room', 'area_sqm', 'numeric(10,2)', 'NUMERIC(10, 2)', 'area_sqm::numeric(10,2)'),
    ('takeoff_symbol_detection', 'symbol_label', 'varchar(100)', 'VARCHAR(100)', None),
    ('takeoff_symbol_detection', 'product_description', 'varchar(255)', 'VARCHAR(255)', None),
    ('takeoff_symbol_template', 'label', 'varchar(100)', 'VARCHAR(100)', None),
    ('takeoff_symbol_template', 'color', 'varchar(7)', 'VARCHAR(7)', None),
    ('takeoff_symbol_template', 'icon', 'varchar(10)', 'VARCHAR(10)', None),
    ('takeoff_symbol_template', 'default_product_description', 'varchar(255)', 'VARCHAR(255)', None),
    ('takeoff_symbol_template', 'default_unit_cost', 'numeric(10,4)', 'NUMERIC(10, 4)', 'default_unit_cost::numeric(10,4)'),
    ('takeoff_symbol_template', 'default_unit_sell', 'numeric(10,4)', 'NUMERIC(10, 4)', 'default_unit_sell::numeric(10,4)'),
]

# (table, column) to SET NOT NULL (only if currently nullable)
_NOTNULL_TARGETS = [
    ('takeoff_area', 'points'),
    ('takeoff_cable_run', 'route_points'),
    ('takeoff_room', 'document_id'),
    ('takeoff_symbol_detection', 'symbol_type_id'),
    ('takeoff_symbol_template', 'document_id'),
    ('takeoff_symbol_template', 'symbol_type_id'),
    ('takeoff_symbol_template', 'label'),
]

_VARCHAR_RE = re.compile(r'^varchar\((\d+)\)$')


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("SET lock_timeout = '5s'")
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    def colmap(tbl):
        return {c['name']: c for c in insp.get_columns(tbl)}

    # ---- RUN-TIME PRE-FLIGHT (no DDL yet): collect every blocker, then abort clean if any ----
    violations = []
    for tbl, col, ddl, reflected, _using in _TYPE_TARGETS:
        if tbl not in tables:
            continue
        c = colmap(tbl).get(col)
        if c is None or str(c['type']) == reflected:
            continue  # column absent or already at target -> this ALTER won't run
        m = _VARCHAR_RE.match(ddl)
        if not m:
            continue  # only varchar narrowing has an over-length failure mode
        limit = int(m.group(1))
        n = bind.execute(
            sa.text(f'SELECT count(*) FROM "{tbl}" WHERE char_length("{col}") > :lim'),
            {'lim': limit},
        ).scalar()
        if n:
            violations.append(f'{tbl}.{col}: {n} row(s) longer than varchar({limit})')

    for tbl, col in _NOTNULL_TARGETS:
        if tbl not in tables:
            continue
        c = colmap(tbl).get(col)
        if c is None or not c['nullable']:
            continue  # column absent or already NOT NULL -> this ALTER won't run
        n = bind.execute(
            sa.text(f'SELECT count(*) FROM "{tbl}" WHERE "{col}" IS NULL')
        ).scalar()
        if n:
            violations.append(f'{tbl}.{col}: {n} NULL row(s) block SET NOT NULL')

    if violations:
        raise RuntimeError(
            'Reconcile C pre-flight aborted — NO schema change applied. Backfill/trim these rows, '
            'then re-run:\n  - ' + '\n  - '.join(violations)
        )

    # ---- All clear: apply (still only-if-needed) ----
    for tbl, col, ddl, reflected, using in _TYPE_TARGETS:
        if tbl not in tables:
            continue
        c = colmap(tbl).get(col)
        if c is None or str(c['type']) == reflected:
            continue
        using_sql = f' USING {using}' if using else ''
        op.execute(f'ALTER TABLE {tbl} ALTER COLUMN {col} TYPE {ddl}{using_sql}')

    for tbl, col in _NOTNULL_TARGETS:
        if tbl not in tables:
            continue
        c = colmap(tbl).get(col)
        if c is not None and c['nullable']:
            op.execute(f'ALTER TABLE {tbl} ALTER COLUMN {col} SET NOT NULL')


def downgrade():
    # Reconciliation only widens/tightens to match prod's existing shape; no destructive reverse.
    # Drop the NOT NULLs we may have added (safe, non-destructive); leave types as-is.
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for tbl, col in _NOTNULL_TARGETS:
        if tbl in tables:
            op.execute(f'ALTER TABLE {tbl} ALTER COLUMN {col} DROP NOT NULL')
