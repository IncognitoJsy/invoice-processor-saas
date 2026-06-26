#!/usr/bin/env bash
# Prove reconcile_d is a TRUE no-op on the prod schema: load a COPY of prod (not prod), snapshot
# columns/tables/indexes, run ONLY reconcile_d (DB is at reconcile_c_qb_types), snapshot again,
# and assert the schema is byte-identical before/after (0 tables, 0 columns, 0 indexes created).
# Read-only against prod (schema dump only). create_all is neutralised so the diff is purely
# reconcile_d's effect.
set -euo pipefail

PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54321
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
[ -n "${SRC_URL:-}" ] || { echo "FATAL: SRC_URL not set"; exit 2; }

TMP="$(mktemp -d /tmp/recdidem.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres prodcopy
CP_URL="postgresql://postgres@/prodcopy?host=$TMP&port=$PORT"

echo "== load COPY of prod schema (schema-only dump + alembic_version row) =="
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$SRC_URL" > "$TMP/schema.sql"
"$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$SRC_URL" > "$TMP/ver.sql"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/schema.sql" >/dev/null
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/ver.sql" >/dev/null
echo -n "   prodcopy alembic head BEFORE: "; "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc "SELECT version_num FROM alembic_version;"

snap(){ # $1 = label suffix
  "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc \
    "SELECT table_name||'.'||column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;" > "$TMP/cols.$1"
  "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc \
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1;" > "$TMP/tbls.$1"
  "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc \
    "SELECT tablename||'.'||indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1;" > "$TMP/idx.$1"
}

echo "== snapshot BEFORE =="
snap before

echo "== run reconcile_d only (create_all neutralised; DB at reconcile_c -> runs reconcile_d) =="
cd "$REPO"
DATABASE_URL="$CP_URL" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -vE "flask_limiter|warnings.warn|WhiteNoise|No directory|SAWarning|Invoice Processor startup|SCHEMA GUARD|compare_metadata" | tail -4
echo -n "   prodcopy alembic head AFTER:  "; "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc "SELECT version_num FROM alembic_version;"

echo "== snapshot AFTER =="
snap after

echo
echo "### tables created by reconcile_d (expect NONE):"; comm -13 "$TMP/tbls.before" "$TMP/tbls.after" | sed 's/^/   + /' || true
echo "### columns added by reconcile_d (expect NONE):";  comm -13 "$TMP/cols.before" "$TMP/cols.after" | sed 's/^/   + /' || true
echo "### indexes created by reconcile_d (expect NONE):"; comm -13 "$TMP/idx.before"  "$TMP/idx.after"  | sed 's/^/   + /' || true
echo "### anything dropped (expect NONE):"; comm -23 "$TMP/tbls.before" "$TMP/tbls.after" | sed 's/^/   - /'; comm -23 "$TMP/cols.before" "$TMP/cols.after" | sed 's/^/   - /'; comm -23 "$TMP/idx.before" "$TMP/idx.after" | sed 's/^/   - /'
T=$(comm -13 "$TMP/tbls.before" "$TMP/tbls.after" | wc -l|tr -d ' '); C=$(comm -13 "$TMP/cols.before" "$TMP/cols.after" | wc -l|tr -d ' '); I=$(comm -13 "$TMP/idx.before" "$TMP/idx.after" | wc -l|tr -d ' ')
D=$(comm -23 "$TMP/cols.before" "$TMP/cols.after" | wc -l|tr -d ' ')
echo
echo "tables_created=$T columns_added=$C indexes_created=$I dropped=$D"
[ "$T" = 0 ] && [ "$C" = 0 ] && [ "$I" = 0 ] && [ "$D" = 0 ] && echo "RESULT: TRUE NO-OP on prod schema (reconcile_d safe to ship to prod)" || echo "RESULT: reconcile_d CHANGED the prod-copy schema — investigate"
