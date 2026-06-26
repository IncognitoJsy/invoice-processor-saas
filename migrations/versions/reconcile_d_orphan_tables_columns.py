"""Reconcile D — create orphan tables + add orphan columns that create_all built but migrations never did.

Closes AUDIT risk #10 Phase 4 prerequisite: a from-empty `alembic upgrade head` was missing 5 tables
and 93 columns vs prod (all created only by app/__init__.py's db.create_all + inline ALTERs). This
migration makes migrations reproduce the models exactly, so create_all can later be removed.

Model-driven for byte-identical match to create_all:
  * tables  -> Model.__table__.create(bind, checkfirst=True)  (exact cols/types/FK/index/unique/default)
  * columns -> op.add_column(table, table.c[name]._copy())     (exact type/nullability/default/variant)
  * indexes -> only the index for the 2 index=True orphan COLUMNS we add
               (ix_invoice_bill_status, ix_supplier_account_email); new tables get all their
               indexes via __table__.create. Pre-existing index name/presence drift elsewhere is
               handled separately (reconcile_e index normalization), not here.

Idempotent & non-destructive on upgrade: tables skipped if present, columns added only if absent,
indexes created only if absent. No-op on prod/staging (everything exists); builds only the gap on
an empty DB. Never alters or drops anything on upgrade.

Revision ID: reconcile_d_orphans
Revises: reconcile_c_qb_types
"""
import importlib
import pkgutil

from alembic import op
import sqlalchemy as sa

revision = 'reconcile_d_orphans'  # <=32 chars (alembic_version.version_num is VARCHAR(32))
down_revision = 'reconcile_c_qb_types'
branch_labels = None
depends_on = None

# Orphan tables in FK-dependency order (FK targets user/job_card/customer/customer_invoice already exist).
_TABLE_ORDER = [
    'supplier_quote_session',   # -> user, job_card
    'supplier_quote',           # -> supplier_quote_session, user
    'supplier_quote_item',      # -> supplier_quote_session
    'employee',                 # -> user
    'labour_entry',             # -> user, employee, job_card, customer_invoice, customer
]

# Orphan columns on EXISTING (already-migrated) tables.
_ORPHAN_COLS = {
    'user': ['billing_frequency', 'business_address_line1', 'business_address_line2',
             'business_address_city', 'business_address_postcode', 'business_address_country',
             'business_email', 'business_phone', 'company_registration_number',
             'employer_contribution_rate', 'mfa_enabled', 'mfa_secret', 'mfa_recovery_codes',
             'payment_failed_email_sent', 'paypal_subscription_id', 'pending_subscription_id',
             'vat_number', 'vat_rate', 'vat_registered', 'vat_scheme'],
    'vtq_jobs': ['floor_plan_path', 'floor_plan_filename', 'floor_plan_scale',
                 'floor_plan_paper', 'floor_plan_orientation', 'floor_plan_rooms'],
    'invoice': ['validation_errors', 'bill_status', 'bill_paid_at', 'bill_notes', 'is_receipt'],
    'invoice_item': ['calculated_selling_price', 'qb_selling_price'],
    'supplier_account': ['email'],
    'project_document': ['takeoff_v8_state'],
}


def _metadata():
    """Import every model module so db.metadata is complete (FK targets resolvable)."""
    import app.models as _m
    for _mod in pkgutil.iter_modules(_m.__path__):
        importlib.import_module(f'app.models.{_mod.name}')
    from app.extensions import db
    return db.metadata


def upgrade():
    bind = op.get_bind()
    md = _metadata()
    existing_tables = set(sa.inspect(bind).get_table_names())

    # 1) Orphan tables — exact model definition, FK-dependency order, skip if present.
    for tname in _TABLE_ORDER:
        if tname not in existing_tables:
            md.tables[tname].create(bind, checkfirst=True)

    # 2) Orphan columns on existing tables — add only if absent, exact model column.
    for tname, cols in _ORPHAN_COLS.items():
        have = {c['name'] for c in sa.inspect(bind).get_columns(tname)}
        tbl = md.tables[tname]
        for cname in cols:
            if cname not in have:
                col = tbl.c[cname]._copy()
                if not col.nullable and col.server_default is None and col.default is None:
                    # NOT-NULL orphan column onto a possibly-populated table. A bare
                    # `ADD COLUMN ... NOT NULL` fails (NotNullViolation) on any env whose table
                    # predates the column and already has rows — the latent cross-env create_all
                    # drift that crash-looped Postgres-ot-n on supplier_account.email. Add WITH a
                    # temporary server_default so existing rows satisfy NOT NULL, then DROP the
                    # default so the end state matches the model exactly (NOT NULL, no default).
                    # supplier_account.email is the only such orphan column ('' backfills its rows).
                    tmp = tbl.c[cname]._copy()
                    # Must wrap in DefaultClause — a bare sa.text() assigned to .server_default is
                    # NOT rendered as a column DEFAULT (the add would emit plain NOT NULL and fail).
                    fill = sa.text("''") if isinstance(col.type, sa.String) else sa.text('0')
                    tmp.server_default = sa.DefaultClause(fill)
                    op.add_column(tname, tmp)
                    op.execute(f'ALTER TABLE "{tname}" ALTER COLUMN "{cname}" DROP DEFAULT')
                else:
                    op.add_column(tname, col)

        # 3) Create the index ONLY for orphan columns we just added that the model marks index=True
        #    (e.g. ix_invoice_bill_status, ix_supplier_account_email). Restricted to the added
        #    columns so this stays a true no-op on prod (those columns+indexes already exist there)
        #    and never touches unrelated/legacy indexes on the table.
        existing_idx = {ix['name'] for ix in sa.inspect(bind).get_indexes(tname)}
        for ix in tbl.indexes:
            ixcols = [c.name for c in ix.columns]
            if (ix.name and ix.name not in existing_idx
                    and len(ixcols) == 1 and ixcols[0] in cols):
                op.create_index(ix.name, tname, ixcols, unique=ix.unique)


def downgrade():
    # Reverse only (destructive — deliberate dev action). Drop added columns, then orphan tables.
    bind = op.get_bind()
    md = _metadata()
    for tname, cols in _ORPHAN_COLS.items():
        have = {c['name'] for c in sa.inspect(bind).get_columns(tname)}
        for cname in cols:
            if cname in have:
                op.drop_column(tname, cname)
    existing_tables = set(sa.inspect(bind).get_table_names())
    for tname in reversed(_TABLE_ORDER):
        if tname in existing_tables:
            md.tables[tname].drop(bind, checkfirst=True)
