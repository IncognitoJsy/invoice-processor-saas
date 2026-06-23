#!/usr/bin/env bash
# Verify reconciliation migrations A+B+C against a FRESH snapshot of a live DB on a throwaway PG17
# cluster. Read-only against the source (schema-only dump + alembic_version data). Never prints secrets.
#
# Usage: SRC_URL="<postgres url>"  bash scripts/verify_reconcile_against_snapshot.sh
#   (SRC_URL is consumed from the environment; it is never echoed.)
set -euo pipefail

PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54317
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
FLASK="$REPO/.venv/bin/flask"; [ -x "$FLASK" ] || FLASK="$PY -m flask"

if [ -z "${SRC_URL:-}" ]; then echo "FATAL: SRC_URL not set"; exit 2; fi

TMP="$(mktemp -d /tmp/snapver.XXXXXX)"
PGDATA="$TMP/data"
cleanup() {
  "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "== 1. init throwaway PG17 cluster =="
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres snap
LOCAL="postgresql://postgres@/snap?host=$TMP&port=$PORT"

echo "== 2. dump source schema (PG17 pg_dump, read-only) =="
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$SRC_URL" > "$TMP/schema.sql"
"$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$SRC_URL" > "$TMP/alembic.sql"
CT=$(grep -c "CREATE TABLE" "$TMP/schema.sql" || true)
echo "   schema.sql: $(wc -l < "$TMP/schema.sql") lines, $CT CREATE TABLE"
if [ "$CT" -lt 10 ]; then echo "FATAL: suspiciously small dump (pg_dump version mismatch?)"; exit 3; fi

echo "== 3. load into snapshot =="
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d snap -v ON_ERROR_STOP=1 -q -f "$TMP/schema.sql" >/dev/null
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d snap -v ON_ERROR_STOP=1 -q -f "$TMP/alembic.sql" >/dev/null
echo -n "   source alembic head: "
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d snap -tAc "SELECT version_num FROM alembic_version;"

cd "$REPO"
export DATABASE_URL="$LOCAL"
export FLASK_APP="wsgi:app"
export SCHEMA_GUARD_STRICT=0

echo "== 4. alembic current (before) =="
$FLASK db current 2>/dev/null || true

echo "== 5. flask db upgrade (applies A -> B -> C) =="
$FLASK db upgrade

echo "== 6. alembic current (after) =="
$FLASK db current 2>/dev/null

echo "== 7. flask schema-check (must report 0 structural drift) =="
set +e
$FLASK schema-check
RC=$?
set -e
echo "   schema-check exit code: $RC"
exit $RC
