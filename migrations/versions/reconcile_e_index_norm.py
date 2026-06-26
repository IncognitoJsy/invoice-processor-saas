"""Reconcile E — index normalization: close the 32 index name/presence diffs from the Phase-4 rebuild.

DRAFT / QUEUED. Captures the residual index drift left after reconcile_d (columns + tables are
already byte-matched). Two non-destructive moves so a from-empty migration build and prod converge
on the SAME index set/names:

  * RENAME prod's legacy-named indexes/constraint to the current-model names (ALTER INDEX/CONSTRAINT
    RENAME — no drop/recreate, no data movement). On a fresh build the legacy names don't exist, so
    the renames are skipped (guarded).
  * CREATE-if-absent the prod-only perf indexes the migrations don't otherwise produce (all on the
    flagged-off takeoff feature). On prod they already exist -> skipped; on a fresh build -> created.

Idempotent & non-destructive (rename + create-if-absent only; never drops). Postgres-only.
NOTE: not yet verified-zero — must pass scripts/rebuild_from_migrations_test.sh (index diffs -> 0)
before shipping. Renames prod indexes when it runs (NOT a no-op on prod — that is its purpose),
unlike reconcile_d.

Revision ID: reconcile_e_index_norm
Revises: reconcile_d_orphans
"""
from alembic import op
import sqlalchemy as sa

revision = 'reconcile_e_index_norm'   # <=32 chars
down_revision = 'reconcile_d_orphans'
branch_labels = None
depends_on = None

# prod legacy index name -> current-model index name
_RENAME_INDEXES = [
    ('idx_supplier_account_number', 'ix_supplier_account_account_number'),
    ('idx_supplier_account_supplier', 'ix_supplier_account_supplier_name'),
    ('idx_supplier_account_user', 'ix_supplier_account_user_id'),
    ('ix_sq_session', 'ix_supplier_quote_session_id'),
    ('ix_sqi_session', 'ix_supplier_quote_item_session_id'),
    ('ix_sqs_job', 'ix_supplier_quote_session_job_card_id'),
    ('ix_sqs_user', 'ix_supplier_quote_session_user_id'),
    ('idx_room_project', 'idx_takeoff_room_project'),
    ('ix_takeoff_symbol_template_project_id', 'idx_symbol_template_project'),
]

# unique CONSTRAINT rename (table, prod legacy name, current-model name) — constraint, not plain index
_RENAME_CONSTRAINTS = [
    ('supplier_account', 'supplier_account_supplier_name_account_number_key', 'uq_supplier_account'),
]

# Perf indexes the canonical migrations/models define but PROD lacks (create-if-absent).
# ALL NON-UNIQUE -> plain CREATE INDEX, no constraint/data-integrity change (safe on existing rows).
# On prod: created (prod is missing them). On a fresh build: already present -> skipped.
_CREATE_INDEXES = [
    # (a) prod-only takeoff perf indexes a fresh build otherwise wouldn't have
    ('ix_takeoff_area_project_id', 'takeoff_area', ['project_id']),
    ('ix_takeoff_cable_run_project_id', 'takeoff_cable_run', ['project_id']),
    ('ix_takeoff_room_document_id', 'takeoff_room', ['document_id']),
    ('ix_takeoff_room_project_id', 'takeoff_room', ['project_id']),
    ('ix_takeoff_symbol_detection_document_id', 'takeoff_symbol_detection', ['document_id']),
    ('ix_takeoff_symbol_detection_project_id', 'takeoff_symbol_detection', ['project_id']),
    ('ix_takeoff_symbol_detection_room_id', 'takeoff_symbol_detection', ['room_id']),
    ('ix_takeoff_symbol_detection_symbol_type_id', 'takeoff_symbol_detection', ['symbol_type_id']),
    # (b) model/migration perf indexes PROD is missing (built by create_all from older models).
    #     ix_queued_invoice_dedup is a PLAIN composite index, NOT unique (matches the model+prod).
    ('ix_invoice_document_type', 'invoice', ['document_type']),
    ('ix_labour_entry_customer_id', 'labour_entry', ['customer_id']),
    ('ix_queued_invoice_user_status', 'queued_invoice', ['user_id', 'status']),
    ('ix_queued_invoice_dedup', 'queued_invoice', ['user_id', 'email_message_id', 'original_filename']),
]


def _all_index_names(bind):
    return set(r[0] for r in bind.execute(sa.text(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public'")))


def _all_constraint_names(bind):
    return set(r[0] for r in bind.execute(sa.text(
        "SELECT conname FROM pg_constraint")))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    idx = _all_index_names(bind)
    cons = _all_constraint_names(bind)

    # 1) rename legacy indexes -> model names (only if old present and new absent)
    for old, new in _RENAME_INDEXES:
        if old in idx and new not in idx:
            op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')

    # 2) rename the legacy unique constraint -> model name
    for table, old, new in _RENAME_CONSTRAINTS:
        if old in cons and new not in cons:
            op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')

    # 3) create prod-only perf indexes that migrations don't otherwise make (idempotent)
    idx = _all_index_names(bind)  # refresh after renames
    for name, table, cols in _CREATE_INDEXES:
        if name not in idx:
            op.create_index(name, table, cols)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    idx = _all_index_names(bind)
    for name, _table, _cols in _CREATE_INDEXES:
        if name in idx:
            op.drop_index(name)
    cons = _all_constraint_names(bind)
    for table, old, new in _RENAME_CONSTRAINTS:
        if new in cons and old not in cons:
            op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{new}" TO "{old}"')
    idx = _all_index_names(bind)
    for old, new in _RENAME_INDEXES:
        if new in idx and old not in idx:
            op.execute(f'ALTER INDEX "{new}" RENAME TO "{old}"')
