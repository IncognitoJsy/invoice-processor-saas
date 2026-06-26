#!/usr/bin/env bash
# Verify reconcile_e: (A) from-empty migrations build (D+E) vs a prod copy ALSO advanced to head
# (E applied) — apples-to-apples, target 0 index diffs without touching columns/tables; and
# (B) E's actual effect on the prod copy — which indexes RENAME vs get CREATED vs no-op.
# Read-only against prod (schema + alembic_version dump only).
set -euo pipefail
PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54323
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
[ -n "${SRC_URL:-}" ] || { echo "FATAL: SRC_URL not set"; exit 2; }
TMP="$(mktemp -d /tmp/recE.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres mig
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres prodcopy
cd "$REPO"

cols(){ "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d "$1" -tAc "SELECT table_name||'.'||column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY 1"; }
tbls(){ "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d "$1" -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"; }
idx(){  "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d "$1" -tAc "SELECT tablename||'.'||indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1"; }

echo "== build 'mig' from empty (base -> reconcile_e) =="
DATABASE_URL="postgresql://postgres@/mig?host=$TMP&port=$PORT" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -E "MIGRATIONS-ONLY UPGRADE COMPLETE|Error" | tail -2

echo "== load prod copy (schema + alembic_version row) =="
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$SRC_URL" > "$TMP/s.sql"
"$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$SRC_URL" > "$TMP/v.sql"
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/s.sql" >/dev/null
"$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/v.sql" >/dev/null
echo -n "   prodcopy head BEFORE E: "; "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc "SELECT version_num FROM alembic_version;"
cols prodcopy > "$TMP/p.cols.before"; tbls prodcopy > "$TMP/p.tbls.before"; idx prodcopy > "$TMP/p.idx.before"

echo "== apply E to prod copy (upgrade head; create_all neutralised) =="
DATABASE_URL="postgresql://postgres@/prodcopy?host=$TMP&port=$PORT" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -E "Running upgrade|MIGRATIONS-ONLY UPGRADE COMPLETE|Error" | tail -3
echo -n "   prodcopy head AFTER E:  "; "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres -d prodcopy -tAc "SELECT version_num FROM alembic_version;"
cols prodcopy > "$TMP/p.cols.after"; tbls prodcopy > "$TMP/p.tbls.after"; idx prodcopy > "$TMP/p.idx.after"

echo
echo "### (B) E's EFFECT on the prod copy:"
echo "  columns added:   [$(comm -13 "$TMP/p.cols.before" "$TMP/p.cols.after" | tr '\n' ' ')]"
echo "  columns dropped: [$(comm -23 "$TMP/p.cols.before" "$TMP/p.cols.after" | tr '\n' ' ')]"
echo "  tables added:    [$(comm -13 "$TMP/p.tbls.before" "$TMP/p.tbls.after" | tr '\n' ' ')]"
echo "  index names REMOVED (old):  "; comm -23 "$TMP/p.idx.before" "$TMP/p.idx.after" | sed 's/^/      - /'
echo "  index names ADDED (new):    "; comm -13 "$TMP/p.idx.before" "$TMP/p.idx.after" | sed 's/^/      + /'
echo "  index count: before=$(wc -l <"$TMP/p.idx.before"|tr -d ' ') after=$(wc -l <"$TMP/p.idx.after"|tr -d ' ')"

echo
echo "### (A) from-empty build (D+E)  vs  prod copy AT HEAD (E applied) — target ZERO:"
cols mig > "$TMP/m.cols"; tbls mig > "$TMP/m.tbls"; idx mig > "$TMP/m.idx"
NC=$(comm -3 "$TMP/m.cols" "$TMP/p.cols.after"|wc -l|tr -d ' '); NT=$(comm -3 "$TMP/m.tbls" "$TMP/p.tbls.after"|wc -l|tr -d ' '); NI=$(comm -3 "$TMP/m.idx" "$TMP/p.idx.after"|wc -l|tr -d ' ')
echo "  index in BUILD not PROD+E:"; comm -23 "$TMP/m.idx" "$TMP/p.idx.after" | sed 's/^/      mig-only: /'
echo "  index in PROD+E not BUILD:"; comm -13 "$TMP/m.idx" "$TMP/p.idx.after" | sed 's/^/      prod-only: /'
echo "  TOTALS  column diffs=$NC  table diffs=$NT  index diffs=$NI"
[ "$NC" = 0 ] && [ "$NT" = 0 ] && [ "$NI" = 0 ] && echo "  RESULT: ZERO DIFF (build == prod-at-head)" || echo "  RESULT: DIFF remains"
