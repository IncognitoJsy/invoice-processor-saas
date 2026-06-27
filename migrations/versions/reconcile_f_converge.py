"""Reconcile F — converge indexes + constraints across all envs (final Phase-4 step before create_all removal).

Closes the index/constraint divergence the 2026-06-26 audit found across the canonical from-empty
build and the three live schemas (main prod, staging, Postgres-ot-n). Goal: a fresh from-migrations
build == prod == staging == otn (0 diffs in scripts/index_divergence_audit.sh), so create_all can be
removed safely.

Idempotent, guarded, fix-forward (like reconcile_e — does NOT edit historical migrations). Postgres-only.
Per the settled decisions in docs/schema-phase4-notes.md:
  1. supplier_quote(_item).session_id -> ON DELETE CASCADE (model + here). No-op on prod/otn (already
     cascade); recreates the plain FK on build/staging.
  2. Drop all 8 redundant legacy idx_* (each duplicates an ix_* present everywhere). Fix-forward drop
     rather than editing 5 historical migrations + reconcile_e's rename chain.
  3. customer_invoice_line index: keep ix_customer_invoice_line_invoice_id canonical; rename staging's
     ix_customer_invoice_line_customer_invoice_id to match.
Plus:
  - project(user_id, created_at) index: build is ASC, model + all live are DESC -> recreate DESC
    (guarded; live already DESC so it's a no-op there).
  - create-if-absent the perf indexes lagging envs miss.
  - the 2 UNIQUEs staging lacks + the 4 model FKs build/prod/otn lack — added with a guarded data
    PRE-CHECK as a safety net (pre-checks are 0 today, but a UNIQUE/FK add fails closed on bad data —
    the supplier_account.email lesson).

Revision ID: reconcile_f_converge
Revises: reconcile_e_index_norm
"""
from alembic import op
import sqlalchemy as sa

revision = 'reconcile_f_converge'   # <=32 chars
down_revision = 'reconcile_e_index_norm'
branch_labels = None
depends_on = None

# 2) redundant legacy idx_* to drop everywhere (each duplicates the noted ix_* present in all envs)
_LEGACY_IDX_DROP = [
    'idx_cable_project',            # -> ix_takeoff_cable_run_project_id
    'idx_takeoff_room_project',     # -> ix_takeoff_room_project_id
    'idx_detection_room',           # -> ix_takeoff_symbol_detection_room_id
    'idx_invoice_doc_type',         # -> ix_invoice_document_type
    'idx_invoice_job_ref',          # -> ix_invoice_job_reference
    'idx_item_part_number',         # -> ix_invoice_item_part_number
    'idx_correction_supplier',      # -> ix_part_number_correction_supplier_name
    'idx_material_part_number',     # -> ix_project_material_part_number
]

# create-if-absent perf indexes lagging envs miss: (name, table, cols, unique)
_CREATE_IDX = [
    ('ix_supplier_account_supplier_name', 'supplier_account', ['supplier_name'], False),  # staging lacks
    ('idx_detection_project_symbol', 'takeoff_symbol_detection', ['project_id', 'symbol_type_id'], False),  # staging+otn
    ('idx_symbol_template_project', 'takeoff_symbol_template', ['project_id'], False),  # staging+otn
]

# 3) index renames (legacy/divergent name -> canonical). Guarded: only if old present & new absent.
_RENAME_INDEXES = [
    ('ix_customer_invoice_line_customer_invoice_id', 'ix_customer_invoice_line_invoice_id'),
]

# 1) supplier_quote FKs that must end ON DELETE CASCADE: (table, conname)
_CASCADE_FKS = [
    ('supplier_quote', 'supplier_quote_session_id_fkey'),
    ('supplier_quote_item', 'supplier_quote_item_session_id_fkey'),
]

# FKs that must end ON DELETE SET NULL (model intent): (table, conname, col, ref_table, ref_col).
# queued_invoice.processed_invoice_id is SET NULL on build/staging/otn but plain on prod.
_SETNULL_FKS = [
    ('queued_invoice', 'queued_invoice_processed_invoice_id_fkey', 'processed_invoice_id', 'invoice', 'id'),
]

# 4 model-defined FKs build/prod/otn lack (only staging had them): (conname, table, col, ref_table, ref_col)
_MODEL_FKS = [
    ('invoice_platform_customer_id_fkey', 'invoice', 'platform_customer_id', 'customer', 'id'),
    ('invoice_platform_job_id_fkey', 'invoice', 'platform_job_id', 'job', 'id'),
    ('invoice_job_card_id_fkey', 'invoice', 'job_card_id', 'job_card', 'id'),
    ('customer_invoice_job_card_id_fkey', 'customer_invoice', 'job_card_id', 'job_card', 'id'),
]


def _indexes(bind):
    return set(r[0] for r in bind.execute(sa.text(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public'")))


def _constraints(bind):
    return set(r[0] for r in bind.execute(sa.text("SELECT conname FROM pg_constraint")))


def _index_def(bind, name):
    r = bind.execute(sa.text("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname=:n"),
                     {'n': name}).first()
    return r[0] if r else None


def _scalar(bind, sql):
    return bind.execute(sa.text(sql)).scalar()


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    # --- 1) supplier_quote(_item).session_id -> ON DELETE CASCADE (guarded; no-op where already cascade)
    for table, conname in _CASCADE_FKS:
        deltype = _scalar(bind, f"""
            SELECT confdeltype FROM pg_constraint
            WHERE conname='{conname}' AND conrelid='{table}'::regclass
              AND confrelid='supplier_quote_session'::regclass""")
        if deltype is not None and deltype != 'c':
            op.drop_constraint(conname, table, type_='foreignkey')
            op.create_foreign_key(conname, table, 'supplier_quote_session',
                                  ['session_id'], ['id'], ondelete='CASCADE')

    # --- 1b) FKs that must end ON DELETE SET NULL (guarded; no-op where already set null)
    for table, conname, col, ref_table, ref_col in _SETNULL_FKS:
        deltype = _scalar(bind, f"""
            SELECT confdeltype FROM pg_constraint
            WHERE conname='{conname}' AND conrelid='{table}'::regclass
              AND confrelid='{ref_table}'::regclass""")
        if deltype is not None and deltype != 'n':
            op.drop_constraint(conname, table, type_='foreignkey')
            op.create_foreign_key(conname, table, ref_table, [col], [ref_col], ondelete='SET NULL')

    # --- 2) drop the 8 redundant legacy idx_* everywhere (the ix_* equivalents remain)
    for name in _LEGACY_IDX_DROP:
        op.execute(f'DROP INDEX IF EXISTS "{name}"')

    # --- project(user_id, created_at): canonical DESC (build is ASC; live already DESC -> skip)
    pdef = _index_def(bind, 'idx_project_user_created')
    if pdef is None:
        op.execute('CREATE INDEX "idx_project_user_created" ON project (user_id, created_at DESC)')
    elif 'DESC' not in pdef:
        op.execute('DROP INDEX IF EXISTS "idx_project_user_created"')
        op.execute('CREATE INDEX "idx_project_user_created" ON project (user_id, created_at DESC)')

    # --- customer_invoice.view_token: canonical = UNIQUE CONSTRAINT (..._key) + PLAIN ix_ index.
    # staging shape = a bare UNIQUE index named ix_customer_invoice_view_token, no constraint.
    cons = _constraints(bind)
    if 'customer_invoice_view_token_key' not in cons:
        idx = _indexes(bind)
        if 'ix_customer_invoice_view_token' in idx:
            # this is staging's bare unique index; drop it so the name is free for the plain index
            op.execute('DROP INDEX IF EXISTS "ix_customer_invoice_view_token"')
        dups = _scalar(bind, "SELECT count(*) FROM (SELECT view_token FROM customer_invoice "
                             "WHERE view_token IS NOT NULL GROUP BY view_token HAVING count(*)>1) t")
        if dups and dups > 0:
            raise RuntimeError(f"reconcile_f: {dups} duplicate customer_invoice.view_token groups — "
                               "cannot add UNIQUE (clean data first)")
        op.create_unique_constraint('customer_invoice_view_token_key', 'customer_invoice', ['view_token'])

    # --- 3 + create-if-absent perf indexes (incl. the plain view_token index)
    create_idx = list(_CREATE_IDX) + [
        ('ix_customer_invoice_view_token', 'customer_invoice', ['view_token'], False),
    ]
    idx = _indexes(bind)
    for name, table, cols, uniq in create_idx:
        if name not in idx:
            op.create_index(name, table, cols, unique=uniq)

    # --- supplier_account UNIQUE(supplier_name, account_number) — staging lacks it
    cons = _constraints(bind)
    if 'uq_supplier_account' not in cons:
        dups = _scalar(bind, "SELECT count(*) FROM (SELECT supplier_name, account_number FROM "
                             "supplier_account GROUP BY supplier_name, account_number HAVING count(*)>1) t")
        if dups and dups > 0:
            raise RuntimeError(f"reconcile_f: {dups} duplicate supplier_account (supplier_name,"
                               "account_number) groups — cannot add UNIQUE (clean data first)")
        op.create_unique_constraint('uq_supplier_account', 'supplier_account',
                                    ['supplier_name', 'account_number'])

    # --- 4 model-defined FKs build/prod/otn lack (guarded + orphan pre-check; staging already has them)
    cons = _constraints(bind)
    for conname, table, col, ref_table, ref_col in _MODEL_FKS:
        if conname in cons:
            continue
        orphans = _scalar(bind, f'SELECT count(*) FROM "{table}" t WHERE t."{col}" IS NOT NULL '
                                f'AND NOT EXISTS (SELECT 1 FROM "{ref_table}" r WHERE r."{ref_col}"=t."{col}")')
        if orphans and orphans > 0:
            raise RuntimeError(f"reconcile_f: {orphans} orphan rows in {table}.{col} -> {ref_table}."
                               f"{ref_col} — cannot add FK (clean data first)")
        op.create_foreign_key(conname, table, ref_table, [col], [ref_col])

    # --- index renames (legacy/divergent -> canonical); guarded
    idx = _indexes(bind)
    for old, new in _RENAME_INDEXES:
        if old in idx and new not in idx:
            op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')


def downgrade():
    # Dev-only best-effort reverse (non-authoritative). Postgres-only.
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    idx = _indexes(bind)
    for old, new in _RENAME_INDEXES:
        if new in idx and old not in idx:
            op.execute(f'ALTER INDEX "{new}" RENAME TO "{old}"')
    cons = _constraints(bind)
    for conname, table, col, ref_table, ref_col in _MODEL_FKS:
        if conname in cons:
            op.drop_constraint(conname, table, type_='foreignkey')
    # leave the UNIQUE constraints + recreated perf indexes + cascade FKs in place (harmless, owned by
    # later canonical state); recreate the dropped legacy idx_* so a downgrade restores prior names.
    idx = _indexes(bind)
    legacy_recreate = [
        ('idx_cable_project', 'takeoff_cable_run', ['project_id']),
        ('idx_takeoff_room_project', 'takeoff_room', ['project_id']),
        ('idx_detection_room', 'takeoff_symbol_detection', ['room_id']),
        ('idx_invoice_doc_type', 'invoice', ['document_type']),
        ('idx_invoice_job_ref', 'invoice', ['job_reference']),
        ('idx_item_part_number', 'invoice_item', ['part_number']),
        ('idx_correction_supplier', 'part_number_correction', ['supplier_name']),
        ('idx_material_part_number', 'project_material', ['part_number']),
    ]
    for name, table, cols in legacy_recreate:
        if name not in idx:
            op.create_index(name, table, cols)
