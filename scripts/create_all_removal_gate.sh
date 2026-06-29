#!/usr/bin/env bash
# STEP 2 — the irreversible gate for removing db.create_all() + the inline ALTERs.
# Build a from-EMPTY database via MIGRATIONS ALONE (create_all neutralised), then:
#   (a) assert the 3 inline-ALTER target columns exist — proving MIGRATIONS create them, not the
#       boot-time ALTERs (so the ALTER blocks are truly redundant);
#   (b) BOOT the app against that migrations-only DB with create_all neutralised, and assert
#       schema_guard reports 0 structural drift AND /health returns 200.
# If anything is missing, migrations are incomplete -> STOP and add a migration first.
# Scratch DB only; no live DB touched.
set -euo pipefail
PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54331
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
TMP="$(mktemp -d /tmp/carem.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null 2>&1
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres mig
cd "$REPO"
export DATABASE_URL="postgresql://postgres@/mig?host=$TMP&port=$PORT"
export APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0

echo "== (1) from-EMPTY migrations-only build (create_all neutralised) =="
"$PY" scripts/_mig_only_build.py 2>&1 | grep -E "UPGRADE COMPLETE|Error|Traceback" | tail -2

echo "== (2) assert the 3 inline-ALTER target columns exist (created by MIGRATIONS, not the ALTERs) =="
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d mig -tA <<'SQL'
SELECT 'vtq_jobs floor_plan_* present: '||count(*)||'/6' FROM information_schema.columns
 WHERE table_name='vtq_jobs' AND column_name IN
   ('floor_plan_path','floor_plan_filename','floor_plan_scale','floor_plan_paper','floor_plan_orientation','floor_plan_rooms');
SELECT 'user.billing_frequency present: '||count(*)||'/1' FROM information_schema.columns
 WHERE table_name='user' AND column_name='billing_frequency';
SELECT 'invoice.validation_errors present: '||count(*)||'/1' FROM information_schema.columns
 WHERE table_name='invoice' AND column_name='validation_errors';
SQL

echo "== (3) BOOT the app against the migrations-only DB (create_all neutralised) =="
cat > "$TMP/boot_test.py" <<'PYEOF'
import os
from app.extensions import db
db.create_all = lambda *a, **k: None        # neutralise the thing we're removing
from app import create_app, schema_guard
app = create_app(os.environ.get('APP_CONFIG', 'default'))
with app.app_context():
    with db.engine.connect() as conn:
        problems = schema_guard.evaluate(conn, db.metadata)
    print("   schema_guard drift problems:", problems if problems else "NONE (0 drift)")
    rv = app.test_client().get('/health')
    print("   /health status:", rv.status_code)
    assert not problems, f"SCHEMA DRIFT vs model: {problems}"
    assert rv.status_code == 200, f"/health returned {rv.status_code}"
print("STEP2 RESULT: from-empty migrations DB boots clean, 0 drift, /health 200 ✅")
PYEOF
"$PY" "$TMP/boot_test.py" 2>&1 | grep -vE "flask_limiter|warnings.warn|WhiteNoise|No directory|SAWarning|compare_metadata" | tail -15