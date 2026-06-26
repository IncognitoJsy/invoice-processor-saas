#!/usr/bin/env bash
# Step 2 gate: build schema from MIGRATIONS-ONLY on an empty scratch DB and diff against a fresh
# PROD snapshot. Zero column/table diff => migrations are the sole authority, safe to remove
# create_all. Any diff => orphans the migrations don't reproduce. Read-only against prod.
set -euo pipefail

PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54319
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
if [ -z "${SRC_URL:-}" ]; then echo "FATAL: SRC_URL (prod public URL) not set"; exit 2; fi

TMP="$(mktemp -d /tmp/rebuildtest.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

echo "== 1. scratch PG17 cluster =="
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres mig
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres prod
MIG_URL="postgresql://postgres@/mig?host=$TMP&port=$PORT"

echo "== 2. MIGRATIONS-ONLY build into 'mig' =="
cd "$REPO"
DATABASE_URL="$MIG_URL" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -vE "flask_limiter|warnings.warn|WhiteNoise|No directory|SAWarning|Invoice Processor startup|SCHEMA GUARD|compare_metadata" | tail -8

echo "== 3. PROD schema snapshot into 'prod' (read-only dump) =="
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$SRC_URL" > "$TMP/prod_schema.sql"
echo "   prod dump: $(grep -c 'CREATE TABLE' "$TMP/prod_schema.sql") tables"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prod -v ON_ERROR_STOP=1 -q -f "$TMP/prod_schema.sql" >/dev/null

echo "== 4. introspect + diff (public schema columns) =="
Q="SELECT table_name||'.'||column_name||'  '||data_type||COALESCE('('||character_maximum_length||')','')||COALESCE(' num('||numeric_precision||','||numeric_scale||')','') FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d mig  -tAc "$Q" > "$TMP/mig.cols"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prod -tAc "$Q" > "$TMP/prod.cols"
TQ="SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1;"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d mig  -tAc "$TQ" > "$TMP/mig.tbls"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prod -tAc "$TQ" > "$TMP/prod.tbls"

echo "   mig columns: $(wc -l < "$TMP/mig.cols") | prod columns: $(wc -l < "$TMP/prod.cols")"
echo
echo "### TABLES in PROD but NOT produced by migrations:"
comm -13 "$TMP/mig.tbls" "$TMP/prod.tbls" | sed 's/^/   - /' || true
echo "### TABLES produced by migrations but NOT in prod:"
comm -23 "$TMP/mig.tbls" "$TMP/prod.tbls" | sed 's/^/   - /' || true
echo
echo "### COLUMNS in PROD but NOT produced by migrations (ORPHANS to capture first):"
comm -13 "$TMP/mig.cols" "$TMP/prod.cols" | sed 's/^/   - /' || true
echo "### COLUMNS produced by migrations but NOT in prod (rebuild adds extra):"
comm -23 "$TMP/mig.cols" "$TMP/prod.cols" | sed 's/^/   - /' || true
echo
IQ="SELECT tablename||'.'||indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1;"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d mig  -tAc "$IQ" > "$TMP/mig.idx"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prod -tAc "$IQ" > "$TMP/prod.idx"
echo "### INDEXES in PROD but NOT produced by migrations:"
comm -13 "$TMP/mig.idx" "$TMP/prod.idx" | sed 's/^/   - /' || true
echo "### INDEXES produced by migrations but NOT in prod:"
comm -23 "$TMP/mig.idx" "$TMP/prod.idx" | sed 's/^/   - /' || true
echo
N=$(comm -3 "$TMP/mig.cols" "$TMP/prod.cols" | wc -l | tr -d ' ')
NT=$(comm -3 "$TMP/mig.tbls" "$TMP/prod.tbls" | wc -l | tr -d ' ')
NI=$(comm -3 "$TMP/mig.idx" "$TMP/prod.idx" | wc -l | tr -d ' ')
echo "TOTAL column diffs: $N ; table diffs: $NT ; index diffs: $NI"
[ "$N" = "0" ] && [ "$NT" = "0" ] && [ "$NI" = "0" ] && echo "RESULT: ZERO DIFF — migrations reproduce prod" || echo "RESULT: DIFF — do NOT remove create_all until migration(s) capture the above"
