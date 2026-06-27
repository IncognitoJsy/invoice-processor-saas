#!/usr/bin/env bash
# Projected 0-diff proof for reconcile_f, PRE-DEPLOY and READ-ONLY.
# The live DBs are still at reconcile_e; index_divergence_audit.sh compares against them directly, so
# it can't show 0 until reconcile_f is deployed. Instead this loads a SCHEMA copy of each live DB
# (read-only dump, no row data), advances each copy to head (applies reconcile_f), and compares all
# four (canonical from-empty build + the 3 advanced copies) with the SAME comparator as the audit.
# 0 diffs here == reconcile_f converges every env. (Live data-safety of the UNIQUE/FK adds was proven
# separately by the read-only pre-checks; schema-only copies have 0 rows so the adds always succeed.)
set -euo pipefail
PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54329
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
for v in PROD_URL STAGING_URL OTN_URL; do eval "[ -n \"\${$v:-}\" ]" || { echo "FATAL: $v not set"; exit 2; }; done
TMP="$(mktemp -d /tmp/recfverify.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null 2>&1
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
cd "$REPO"
PSQL(){ "$PGBIN/psql" -h "$TMP" -p "$PORT" -U postgres "$@"; }

build_to_head(){ # $1=dbname
  DATABASE_URL="postgresql://postgres@/$1?host=$TMP&port=$PORT" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
    "$PY" scripts/_mig_only_build.py 2>&1 | grep -E "Running upgrade reconcile_f|UPGRADE COMPLETE|Error|RuntimeError|reconcile_f:" | tail -4 >&2
}

echo "== canonical 'mig' (base -> reconcile_f) ==" >&2
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres mig
build_to_head mig

for pair in "prod:$PROD_URL" "staging:$STAGING_URL" "otn:$OTN_URL"; do
  env="${pair%%:*}"; url="${pair#*:}"
  echo "== ${env}copy: load live schema (read-only), advance to head (apply reconcile_f) ==" >&2
  "$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres "${env}copy"
  "$PGBIN/pg_dump" --schema-only --no-owner --no-privileges "$url" > "$TMP/$env.sql"
  "$PGBIN/pg_dump" --data-only --no-owner --table=alembic_version "$url" > "$TMP/$env.ver.sql"
  PSQL -d "${env}copy" -v ON_ERROR_STOP=1 -q -f "$TMP/$env.sql" >/dev/null
  PSQL -d "${env}copy" -v ON_ERROR_STOP=1 -q -f "$TMP/$env.ver.sql" >/dev/null
  echo -n "   ${env}copy head BEFORE: " >&2; PSQL -d "${env}copy" -tAc "SELECT version_num FROM alembic_version;" >&2
  build_to_head "${env}copy"
  echo -n "   ${env}copy head AFTER:  " >&2; PSQL -d "${env}copy" -tAc "SELECT version_num FROM alembic_version;" >&2
done

Q_IDX="SELECT tablename, indexname, CASE WHEN indexdef LIKE 'CREATE UNIQUE%' THEN 'UNIQUE' ELSE 'PLAIN' END, regexp_replace(indexdef,'.* USING ','') FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2;"
Q_CON="SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' ORDER BY 1,2;"
Q_NN="SELECT table_name||'.'||column_name, is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;"
emit(){ local env="$1" db="$2"
  PSQL -d "$db" -At -F $'\t' -c "$Q_IDX" > "$TMP/$env.idx"
  PSQL -d "$db" -At -F $'\t' -c "$Q_CON" > "$TMP/$env.con"
  PSQL -d "$db" -At -F $'\t' -c "$Q_NN"  > "$TMP/$env.nn"
}
emit mig mig; emit prod prodcopy; emit staging stagingcopy; emit otn otncopy

# ---- same comparator as index_divergence_audit.sh ----
TMP="$TMP" "$PY" - <<'PYEOF'
import os
T=os.environ['TMP']; ENVS=['mig','prod','staging','otn']
def load(cat):
    d={}
    for e in ENVS:
        d[e]=[ln.rstrip('\n').split('\t') for ln in open(f"{T}/{e}.{cat}") if ln.strip()]
    return d
def mark(s): return ''.join(c if e in s else '·' for e,c in zip(ENVS,['M','P','S','O']))
idx=load('idx'); con=load('con'); nn=load('nn')
print("LEGEND M=build(base->reconcile_f)  P=prodcopy+f  S=stagingcopy+f  O=otncopy+f")
sem={}; semn={}
for e in ENVS:
    for t,n,u,d in idx[e]:
        sem.setdefault((t,u,d),set()).add(e); semn.setdefault((t,u,d),{}).setdefault(e,set()).add(n)
print("\n### INDEX presence diffs:")
r=[(mark(s),k) for k,s in sem.items() if len(s)<4]
print("   (none)" if not r else "")
for m,(t,u,d) in sorted(r,key=lambda x:(x[1][0],x[1][2])): print(f"   {m}  {u:6} {t}.{d}")
print("### INDEX name drift:")
dn=0
for k,em in sorted(semn.items()):
    names=set().union(*em.values())
    if len(names)>1 and len(em)>=2:
        dn+=1; t,u,d=k; print(f"   {u:6} {t}.{d}")
        for e in ENVS:
            if e in em: print(f"      {e}: {','.join(sorted(em[e]))}")
print("   (none)" if not dn else "")
csem={}
for e in ENVS:
    for t,n,ct,d in con[e]: csem.setdefault((t,ct,d),set()).add(e)
print("### CONSTRAINT presence diffs:")
r=[(mark(s),k) for k,s in csem.items() if len(s)<4]
print("   (none)" if not r else "")
for m,(t,ct,d) in sorted(r,key=lambda x:(x[1][1],x[1][0])): print(f"   {m}  [{ct}] {t}: {d}")
cm={}
for e in ENVS:
    for col,v in nn[e]: cm.setdefault(col,{})[e]=v
print("### NOT-NULL / column diffs:")
nd=[c for c in cm if len(cm[c])<4 or len(set(cm[c].values()))>1]
print("   (none)" if not nd else "")
for c in sorted(nd): print(f"   {c}: "+'  '.join('%s=%s'%(e,cm[c].get(e,'ABSENT')) for e in ENVS))
ni=sum(1 for v in sem.values() if len(v)<4); nc=sum(1 for v in csem.values() if len(v)<4)
nn_=len(nd)
print("\n"+"="*70)
print(f"TOTALS  index-diffs={ni}  constraint-diffs={nc}  col/nullability-diffs={nn_}")
print("RESULT: 0 DIFFS ACROSS ALL FOUR ✅" if ni==0 and nc==0 and nn_==0 and dn==0 else "RESULT: DIFFS REMAIN ❌")
print("="*70)
PYEOF