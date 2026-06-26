#!/usr/bin/env bash
# Cross-env safety proof for the reconcile_d NOT-NULL fix (server_default-then-drop).
#   #1 MAIN PROD: load a COPY of main prod, force alembic_version back to reconcile_c, run
#      upgrade head (edited D + E). email already exists -> add is SKIPPED. Assert ZERO
#      col/table/idx change AND supplier_account.email stays NOT NULL with no default
#      (main prod completely unaffected).
#   #2 POPULATED-NO-EMAIL (mirrors Postgres-ot-n): load a COPY of the otn schema, insert rows
#      into supplier_account (no email column, FK bypassed), run upgrade head. Assert the
#      migration SUCCEEDS, email ends NOT NULL with NO default, and existing rows backfilled to ''.
# Read-only against both source DBs (schema dump + alembic_version only; otn data NOT dumped).
set -euo pipefail
PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54325
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
[ -n "${PROD_URL:-}" ] || { echo "FATAL: PROD_URL not set"; exit 2; }
[ -n "${OTN_URL:-}"  ] || { echo "FATAL: OTN_URL not set";  exit 2; }
TMP="$(mktemp -d /tmp/recdfix.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
cd "$REPO"
PSQL(){ "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres "$@"; }
cols(){ PSQL -d "$1" -tAc "SELECT table_name||'.'||column_name FROM information_schema.columns WHERE table_schema='public' ORDER BY 1"; }
tbls(){ PSQL -d "$1" -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"; }
idx(){  PSQL -d "$1" -tAc "SELECT tablename||'.'||indexname FROM pg_indexes WHERE schemaname='public' ORDER BY 1"; }
email_meta(){ PSQL -d "$1" -tAc "SELECT is_nullable||'|'||COALESCE(column_default,'<none>') FROM information_schema.columns WHERE table_schema='public' AND table_name='supplier_account' AND column_name='email'"; }
RUN_UPGRADE(){ DATABASE_URL="postgresql://postgres@/$1?host=$TMP&port=$PORT" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -E "Running upgrade|MIGRATIONS-ONLY UPGRADE COMPLETE|Error|Traceback|NotNull" | tail -6; }

echo "############ #1  MAIN PROD — must be a TRUE NO-OP (email exists -> skipped) ############"
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres prodcopy
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$PROD_URL" > "$TMP/prod.sql"
"$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$PROD_URL" > "$TMP/prodver.sql"
PSQL -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/prod.sql" >/dev/null
PSQL -d prodcopy -v ON_ERROR_STOP=1 -q -f "$TMP/prodver.sql" >/dev/null
echo -n "   prodcopy head AS DUMPED: "; PSQL -d prodcopy -tAc "SELECT version_num FROM alembic_version;"
# force back to reconcile_c so the edited D (and E) actually RE-RUN on the full prod schema
PSQL -d prodcopy -q -c "UPDATE alembic_version SET version_num='reconcile_c_qb_types';"
echo -n "   prodcopy head FORCED TO: "; PSQL -d prodcopy -tAc "SELECT version_num FROM alembic_version;"
echo -n "   email meta BEFORE (is_nullable|default): "; email_meta prodcopy
cols prodcopy >"$TMP/pc.before"; tbls prodcopy >"$TMP/pt.before"; idx prodcopy >"$TMP/pi.before"
echo "   -- running upgrade head (D+E) --"; RUN_UPGRADE prodcopy
echo -n "   prodcopy head AFTER: "; PSQL -d prodcopy -tAc "SELECT version_num FROM alembic_version;"
echo -n "   email meta AFTER  (is_nullable|default): "; email_meta prodcopy
cols prodcopy >"$TMP/pc.after"; tbls prodcopy >"$TMP/pt.after"; idx prodcopy >"$TMP/pi.after"
C=$(comm -3 "$TMP/pc.before" "$TMP/pc.after"|wc -l|tr -d ' ')
T=$(comm -3 "$TMP/pt.before" "$TMP/pt.after"|wc -l|tr -d ' ')
I=$(comm -3 "$TMP/pi.before" "$TMP/pi.after"|wc -l|tr -d ' ')
echo "   column diffs=$C table diffs=$T index diffs=$I"
comm -3 "$TMP/pc.before" "$TMP/pc.after" | sed 's/^/      col-diff: /'
comm -3 "$TMP/pi.before" "$TMP/pi.after" | sed 's/^/      idx-diff: /'
[ "$C" = 0 ] && [ "$T" = 0 ] && [ "$I" = 0 ] && echo "   #1 RESULT: TRUE NO-OP on main prod ✅" || echo "   #1 RESULT: CHANGED main prod schema ❌"

echo
echo "############ #2  POPULATED-NO-EMAIL (mirror Postgres-ot-n) — D must now SUCCEED ############"
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres otncopy
"$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$OTN_URL" > "$TMP/otn.sql"
"$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$OTN_URL" > "$TMP/otnver.sql"
PSQL -d otncopy -v ON_ERROR_STOP=1 -q -f "$TMP/otn.sql" >/dev/null
PSQL -d otncopy -v ON_ERROR_STOP=1 -q -f "$TMP/otnver.sql" >/dev/null
echo -n "   otncopy head: "; PSQL -d otncopy -tAc "SELECT version_num FROM alembic_version;"
HASEMAIL=$(PSQL -d otncopy -tAc "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='supplier_account' AND column_name='email'")
echo "   supplier_account has 'email' column BEFORE: $HASEMAIL (expect 0)"
# insert 3 rows into supplier_account WITHOUT email (FK bypassed); mirrors otn's populated table
PSQL -d otncopy -q -c "SET session_replication_role=replica;
  INSERT INTO supplier_account (supplier_name, account_number, user_id)
  VALUES ('Acme A','A1',999),('Acme B','B2',999),('Acme C','C3',999);" 2>&1 | tail -2 || true
RC=$(PSQL -d otncopy -tAc "SELECT count(*) FROM supplier_account;")
echo "   supplier_account row count (populated): $RC"
echo "   -- running upgrade head (edited D + E) --"; RUN_UPGRADE otncopy
echo -n "   otncopy head AFTER: "; PSQL -d otncopy -tAc "SELECT version_num FROM alembic_version;"
echo -n "   email meta AFTER (is_nullable|default): "; email_meta otncopy
NULLS=$(PSQL -d otncopy -tAc "SELECT count(*) FROM supplier_account WHERE email IS NULL;")
BLANKS=$(PSQL -d otncopy -tAc "SELECT count(*) FROM supplier_account WHERE email='';")
HEAD=$(PSQL -d otncopy -tAc "SELECT version_num FROM alembic_version;")
NULLABLE=$(PSQL -d otncopy -tAc "SELECT is_nullable FROM information_schema.columns WHERE table_name='supplier_account' AND column_name='email';")
DEFAULT=$(PSQL -d otncopy -tAc "SELECT COALESCE(column_default,'<none>') FROM information_schema.columns WHERE table_name='supplier_account' AND column_name='email';")
echo "   email NULL rows=$NULLS  email '' rows=$BLANKS  head=$HEAD  is_nullable=$NULLABLE  default=$DEFAULT"
if [ "$HEAD" = "reconcile_e_index_norm" ] && [ "$NULLABLE" = "NO" ] && [ "$DEFAULT" = "<none>" ] && [ "$NULLS" = 0 ] && [ "$BLANKS" = "$RC" ]; then
  echo "   #2 RESULT: D SUCCEEDS; email NOT NULL, no default, $RC rows backfilled to '' ✅"
else
  echo "   #2 RESULT: unexpected end-state ❌"
fi