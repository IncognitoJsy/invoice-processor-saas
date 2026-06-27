#!/usr/bin/env bash
# READ-ONLY audit: index + constraint + NOT-NULL divergence across the canonical from-empty
# migrations build (D+E) and the THREE live schemas (main prod, staging, Postgres-ot-n).
# Only the canonical build uses a scratch cluster; the three live DBs are queried directly
# against the system catalogs (SELECT only — no row data, no writes, no dumps loaded).
set -euo pipefail
PGBIN=/opt/homebrew/opt/postgresql@17/bin
PORT=54327
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY=python3
for v in PROD_URL STAGING_URL OTN_URL; do eval "[ -n \"\${$v:-}\" ]" || { echo "FATAL: $v not set"; exit 2; }; done
TMP="$(mktemp -d /tmp/idxaudit.XXXXXX)"; PGDATA="$TMP/data"
cleanup(){ "$PGBIN/pg_ctl" -D "$PGDATA" stop -m immediate >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

# 1) canonical from-empty build (base -> reconcile_e) in a scratch cluster
"$PGBIN/initdb" -D "$PGDATA" -U postgres -A trust >/dev/null 2>&1
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/pg.log" -w start >/dev/null
"$PGBIN/createdb" -h "$TMP" -p "$PORT" -U postgres mig
cd "$REPO"
echo "== building canonical 'mig' (base -> reconcile_e) ==" >&2
DATABASE_URL="postgresql://postgres@/mig?host=$TMP&port=$PORT" APP_CONFIG=default PYTHONPATH="$REPO" SCHEMA_GUARD_STRICT=0 \
  "$PY" scripts/_mig_only_build.py 2>&1 | grep -E "UPGRADE COMPLETE|Error" | tail -1 >&2

MIG_CONN=(-h "$TMP" -p "$PORT" -U postgres -d mig)

Q_IDX="SELECT tablename, indexname, CASE WHEN indexdef LIKE 'CREATE UNIQUE%' THEN 'UNIQUE' ELSE 'PLAIN' END, regexp_replace(indexdef,'.* USING ','') FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2;"
Q_CON="SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' ORDER BY 1,2;"
Q_NN="SELECT table_name||'.'||column_name, is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;"

dump(){ # $1=env label ; rest = psql conn args
  local env="$1"; shift
  "$PGBIN/psql" "$@" -At -F $'\t' -c "$Q_IDX" > "$TMP/$env.idx"
  "$PGBIN/psql" "$@" -At -F $'\t' -c "$Q_CON" > "$TMP/$env.con"
  "$PGBIN/psql" "$@" -At -F $'\t' -c "$Q_NN"  > "$TMP/$env.nn"
  echo "   $env: idx=$(wc -l <"$TMP/$env.idx"|tr -d ' ') con=$(wc -l <"$TMP/$env.con"|tr -d ' ') cols=$(wc -l <"$TMP/$env.nn"|tr -d ' ')" >&2
}
echo "== introspecting (read-only) ==" >&2
dump mig    "${MIG_CONN[@]}"
dump prod    "$PROD_URL"
dump staging "$STAGING_URL"
dump otn     "$OTN_URL"

TMP="$TMP" "$PY" - <<'PYEOF'
import os
T=os.environ['TMP']
ENVS=['mig','prod','staging','otn']
def load(cat):
    d={}
    for e in ENVS:
        rows=[]
        for ln in open(f"{T}/{e}.{cat}"):
            ln=ln.rstrip('\n')
            if ln: rows.append(ln.split('\t'))
        d[e]=rows
    return d
def mark(envset): return ''.join(c if e in envset else '·' for e,c in zip(ENVS,['M','P','S','O']))

idx=load('idx'); con=load('con'); nn=load('nn')

print("="*92)
print("LEGEND: M=canonical from-empty build (D+E)   P=main prod   S=staging   O=Postgres-ot-n")
print("        a row is shown ONLY where the four do not agree.  '·' = absent in that env.")
print("="*92)

# ---------- INDEXES ----------
# semantic signature = (table, UNIQUE/PLAIN, def-without-name); named = table.indexname
sem={}      # sig -> set(env)
sem_names={}# sig -> {env: set(names)}
named={}    # table.name -> set(env)
for e in ENVS:
    for table,name,uniq,defn in idx[e]:
        sig=(table,uniq,defn)
        sem.setdefault(sig,set()).add(e)
        sem_names.setdefault(sig,{}).setdefault(e,set()).add(name)
        named.setdefault(f"{table}.{name}",set()).add(e)

print("\n### 1A. INDEX PRESENCE DIFFS (same column-set+uniqueness, missing in ≥1 env)")
rows=[(mark(envs),sig) for sig,envs in sem.items() if len(envs)<4]
if not rows: print("   (none — every env has the same set of index column-signatures)")
for m,(table,uniq,defn) in sorted(rows, key=lambda r:(r[1][0],r[1][2])):
    print(f"   {m}  {uniq:6} {table}.{defn}")

print("\n### 1B. INDEX NAME DRIFT (same column-signature present in ≥2 envs, but NAMED differently)")
drift=0
for sig,envmap in sorted(sem_names.items()):
    allnames=set().union(*envmap.values())
    if len(allnames)>1 and len(envmap)>=2:
        table,uniq,defn=sig; drift+=1
        print(f"   {uniq:6} {table}.{defn}")
        for e in ENVS:
            if e in envmap: print(f"        {e:8} -> {', '.join(sorted(envmap[e]))}")
if not drift: print("   (none — matching indexes share the same name across envs)")

# ---------- CONSTRAINTS ----------
CT={'p':'PRIMARY KEY','u':'UNIQUE','f':'FOREIGN KEY','c':'CHECK','x':'EXCLUDE'}
csem={}; csem_names={}
for e in ENVS:
    for table,name,ctype,defn in con[e]:
        sig=(table,ctype,defn)
        csem.setdefault(sig,set()).add(e)
        csem_names.setdefault(sig,{}).setdefault(e,set()).add(name)

print("\n### 2A. CONSTRAINT PRESENCE DIFFS (PK / UNIQUE / FK / CHECK missing in ≥1 env)")
rows=[(mark(envs),sig) for sig,envs in csem.items() if len(envs)<4]
if not rows: print("   (none — identical constraint sets across all four)")
for m,(table,ctype,defn) in sorted(rows, key=lambda r:(r[1][1],r[1][0])):
    flag=' 🔒' if ctype in ('u','p') else ''
    print(f"   {m}  [{CT.get(ctype,ctype)}]{flag} {table}: {defn}")

print("\n### 2B. CONSTRAINT NAME DRIFT (same definition, named differently across envs)")
drift=0
for sig,envmap in sorted(csem_names.items()):
    allnames=set().union(*envmap.values())
    if len(allnames)>1 and len(envmap)>=2:
        table,ctype,defn=sig; drift+=1
        print(f"   [{CT.get(ctype,ctype)}] {table}: {defn}")
        for e in ENVS:
            if e in envmap: print(f"        {e:8} -> {', '.join(sorted(envmap[e]))}")
if not drift: print("   (none)")

# ---------- NOT-NULL / column presence ----------
colmap={}  # col -> {env: YES/NO}
for e in ENVS:
    for col,isnull in nn[e]:
        colmap.setdefault(col,{})[e]=isnull
print("\n### 3. NOT-NULL / COLUMN-PRESENCE DIFFS (correctness — the supplier_account.email class)")
diffs=0
for col in sorted(colmap):
    em=colmap[col]
    present=set(em)
    nullvals=set(em.values())
    if len(present)<4 or len(nullvals)>1:
        diffs+=1
        cells=[]
        for e in ENVS:
            cells.append(f"{e}={em.get(e,'ABSENT')}")
        tag=' 🔒NULLABILITY-DIFF' if len(nullvals)>1 and len(present)>1 else ''
        print(f"   {col}: {'  '.join(cells)}{tag}")
if not diffs: print("   (none — identical column sets and nullability across all four)")

# ---------- summary counts ----------
print("\n"+"="*92)
def cnt(d): return sum(1 for v in d.values() if len(v)<4)
print(f"SUMMARY  index-presence-diffs={cnt(sem)}  constraint-presence-diffs={cnt(csem)}  "
      f"col/nullability-diffs={sum(1 for c in colmap.values() if len(c)<4 or len(set(c.values()))>1)}")
print("="*92)
PYEOF