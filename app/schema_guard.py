"""Schema-drift guardrail (AUDIT risk #10).

Detects when the live DB schema diverges from the models/migrations, so a future migration can't
silently surprise-fail the way the invoice_item.created_at outage did. Reports only STRUCTURAL
drift (tables/columns/types/nullability) and deliberately IGNORES the autogenerate noise that is
not real drift here:
  - server-default differences (models use Python-side default=, DB carries server defaults),
  - index and foreign-key NAME differences.

Use:
  * `flask schema-check`  — CI / pre-deploy gate; exits non-zero on drift or if not at Alembic head.
  * check_and_log(app)    — called at boot; logs CRITICAL on drift (never raises unless
                            SCHEMA_GUARD_STRICT=1) so it can't itself cause an outage.
"""
import logging
import os

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)

# Only these op types are treated as real drift; everything else (modify_default, add/remove_index,
# add/remove_fk, *_constraint) is autogenerate noise for our schema.
_STRUCTURAL = {'add_table', 'remove_table', 'add_column', 'remove_column',
               'modify_type', 'modify_nullable'}


def _fmt(x):
    op = x[0]
    if op in ('add_table', 'remove_table'):
        return f"{op}: {x[1].name}"
    if op in ('add_column', 'remove_column'):
        return f"{op}: {x[2]}.{x[3].name} ({x[3].type})"
    if op == 'modify_type':
        return f"modify_type: {x[2]}.{x[3]}  db={x[-2]} -> model={x[-1]}"
    if op == 'modify_nullable':
        return f"modify_nullable: {x[2]}.{x[3]}  db_null={x[-2]} -> model_null={x[-1]}"
    return str(x)


def structural_drift(connection, metadata):
    """Return human-readable structural-drift items (models vs the connected DB), noise filtered."""
    ctx = MigrationContext.configure(connection, opts={'compare_type': True})
    out = []
    for d in compare_metadata(ctx, metadata):
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, tuple) and x and x[0] in _STRUCTURAL:
                out.append(_fmt(x))
    return out


def head_revision(script_location='migrations'):
    cfg = Config()
    cfg.set_main_option('script_location', script_location)
    return ScriptDirectory.from_config(cfg).get_current_head()


def current_revision(connection):
    return MigrationContext.configure(connection).get_current_revision()


def evaluate(connection, metadata, script_location='migrations'):
    """Return (problems:list[str]). Empty list == healthy (at head, no structural drift)."""
    problems = []
    cur, head = current_revision(connection), head_revision(script_location)
    if cur != head:
        problems.append(f"DB at revision {cur!r}, Alembic head is {head!r} — not up to date")
    problems.extend(structural_drift(connection, metadata))
    return problems


def check_and_log(app):
    """Boot-time guard: log loudly on drift. Never raises unless SCHEMA_GUARD_STRICT=1 (so the
    guard itself can't take prod down — the lesson from the migration outage)."""
    from app.extensions import db
    try:
        with db.engine.connect() as conn:
            problems = evaluate(conn, db.metadata)
    except Exception as e:
        app.logger.warning(f"SCHEMA GUARD: check skipped ({type(e).__name__}: {e})")
        return []
    if problems:
        app.logger.critical("SCHEMA GUARD: drift detected vs models/migrations:\n  - "
                            + "\n  - ".join(problems))
        if os.environ.get('SCHEMA_GUARD_STRICT') == '1':
            raise RuntimeError("Schema drift detected and SCHEMA_GUARD_STRICT=1")
    else:
        app.logger.info("SCHEMA GUARD: OK — DB at Alembic head, no structural drift")
    return problems


def register_cli(app):
    @app.cli.command('schema-check')
    def schema_check():  # pragma: no cover - exercised via CI, not unit tests
        """Fail (exit 1) if the DB isn't at Alembic head with no structural drift vs the models."""
        import sys
        from app.extensions import db
        with db.engine.connect() as conn:
            problems = evaluate(conn, db.metadata)
        if problems:
            print("SCHEMA DRIFT / not-at-head:")
            for p in problems:
                print(f"  - {p}")
            sys.exit(1)
        print("schema-check OK: at Alembic head, no structural drift")
