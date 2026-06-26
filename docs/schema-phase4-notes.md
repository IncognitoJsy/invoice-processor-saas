# Schema Phase 4 — notes & the open blocker for the `create_all` removal session

Context: AUDIT risk #10 Phase 4 = make Alembic migrations the **sole** schema authority, then remove
`db.create_all()` + the 3 inline `ALTER` blocks from `app/__init__.py` (~L46–78).

## Done so far
- **reconcile_d_orphans** (live on prod + staging): created the 5 orphan tables (`employee`,
  `labour_entry`, `supplier_quote`, `supplier_quote_item`, `supplier_quote_session`) + 35 orphan
  columns the models/`create_all` had but no migration created. Proven no-op on prod & staging.
- **reconcile_e_index_norm** (live on staging; → prod): index normalization — 10 RENAMEs
  (legacy → current-model names) + 12 non-unique `CREATE INDEX`-if-absent. Verified:
  **from-empty build (D+E) == prod-copy advanced to E → 0 column / 0 table / 0 index diff.**

## 🚧 OPEN BLOCKER — resolve BEFORE the `create_all` removal session
The removal premise is **"a fresh from-migrations build == prod"** (so removing `create_all` is safe
for prod and any new env). We proved that for **prod**. But shipping E to **staging** revealed that
**staging and prod have *independent*, divergent index drift** — i.e. `create_all` has produced
*different* schemas across environments over time. So **fresh-build == prod does NOT imply
fresh-build == staging**, and "envs are interchangeable" is false today.

Observed on **2026-06-26** (staging at reconcile_e vs prod at reconcile_d, before E on prod):
- **Index count:** staging **131** vs canonical from-empty build **139** (prod after E == 139).
- **Same column, different index NAME across envs**, e.g. `customer_invoice_line`:
  prod `ix_customer_invoice_line_invoice_id` vs staging `ix_customer_invoice_line_customer_invoice_id`.
- **prod-only indexes not in the canonical build and not handled by E:**
  `takeoff_cable_run.idx_cable_project`, `takeoff_symbol_detection.idx_detection_project_symbol`,
  `takeoff_symbol_detection.idx_detection_room`, `customer_invoice.customer_invoice_view_token_key`.
- Staging was clearly built by `create_all` from a **newer** model than prod (staging already had
  the current model-name indexes; prod had the legacy names E renames). E behaved correctly
  (renames guarded/skipped where legacy names absent; nothing dropped) — this is not a regression,
  but it shows the env schemas are not identical.

### What this means for the removal session
- We have proven **build == prod** (after E). We have NOT proven **build == staging**, and we now
  know it isn't.
- Before removing `create_all`, decide the canonical target and reconcile the stragglers:
  1. Should the canonical build carry the prod-only indexes (`idx_cable_project`,
     `idx_detection_*`, `customer_invoice_view_token_key`)? If yes → add them to the models/a
     migration. If they're redundant → drop on prod (separate, gated).
  2. Resolve the `customer_invoice_line` index-name divergence (pick one name; rename the other).
  3. Re-run `scripts/rebuild_from_migrations_test.sh` against **both** a prod snapshot **and** a
     staging snapshot; require 0 diff on **both** before removing `create_all`.
- Until that's 0-diff on both envs, removing `create_all` risks a fresh/rebuilt env not matching a
  live one.

## 🚩 Deploy topology — there are THREE create_all'd databases, and prod is TWO targets
**Both production app services auto-deploy from `master`:**
- **GoZappify** (gozappify.com) → DB `Postgres` (main prod).
- **invoice-processor-saas** (the Intuit-test instance) → DB **`Postgres-ot-n`**.

So **a single `master` merge redeploys BOTH apps**, each running `flask db upgrade` against its own
database. (Staging is a separate environment: GoZappify@staging deploys from `staging` → its own
staging `Postgres`.) That's **three** independently-`create_all`'d schemas with divergent histories.

This is exactly what turned the reconcile_d NOT-NULL bug into a **two-target incident** (resolved
2026-06-26): `reconcile_d` added `supplier_account.email` by copying the model's `NOT NULL`. On main
prod the column already existed (created when the table was empty) so the add was skipped; on
`Postgres-ot-n` the table predated the column **and already had rows**, so `ADD COLUMN ... NOT NULL`
hit `NotNullViolation` and crash-looped the second app. Fix: add NOT-NULL orphan columns WITH a
temporary `server_default` (`sa.DefaultClause`), then drop the default (see
`scripts/reconcile_d_fix_verify.sh`).

**Standing consideration for the create_all-removal session (and every future migration):**
- A migration that's a clean no-op on main prod can still **fail on `Postgres-ot-n`** — it has its
  own, older `create_all` history. Any new/edited migration must be proven safe on **Postgres-ot-n
  too**, not just main prod and staging.
- The "0-diff on both envs" gate above must become **0-diff on all THREE** (main prod, staging,
  Postgres-ot-n) before `create_all` is removed — otherwise a fresh from-migrations build won't
  match the second prod app's live schema.

## 📋 Full divergence audit (2026-06-26) — written scope for the reconcile_f / removal session
Read-only audit of indexes + constraints + nullability across **all four** schemas (canonical
from-empty build `mig`, main prod, staging, Postgres-ot-n) via `scripts/index_divergence_audit.sh`.
Object counts: mig 139 idx / 124 con, prod 139 / 124, staging 131 / 126, otn 134 / 124. **Columns
and NOT-NULL are identical across all four (698, 0 diffs) — the supplier_account.email class is
fully closed; all remaining drift is indexes + constraints.** Staging is the major outlier (built by
create_all from a *newer* model); otn lags only on takeoff perf indexes + legacy dupes.

### 🔒 Correctness divergences (behaviour, not just perf-index naming — fix carefully)
1. **2 UNIQUE constraints MISSING on staging:** `customer_invoice(view_token)` and
   `supplier_account(supplier_name, account_number)`. Staging is not enforcing uniqueness the model
   intends (view_token enforced only by a bare unique *index* named `ix_customer_invoice_view_token`,
   no backing constraint; supplier_account dedup not enforced at all). Adding these on staging is
   data-unsafe — **must pre-check for duplicate rows or the add fails closed (the email lesson).**
2. **2 FK `ON DELETE` mismatches:**
   - `queued_invoice.processed_invoice_id→invoice`: model = `ondelete='SET NULL'`; build/staging/otn
     correct; **prod diverges (plain)** → prod would RESTRICT an invoice delete others would null.
   - `supplier_quote.session_id` & `supplier_quote_item.session_id`: model = **plain (no ondelete)**;
     build + staging correct; **prod + otn carry an extra `ON DELETE CASCADE` the model doesn't
     declare.** (See open decision below.)
3. **4 model-defined FKs unenforced on mig/prod/otn** (only staging realised them): `invoice.
   platform_customer_id→customer`, `invoice.platform_job_id→job`, `invoice.job_card_id→job_card`,
   `customer_invoice.job_card_id→job_card`. Columns exist everywhere; the FK constraints were never
   migrated. Adding them is data-unsafe — **must pre-check for orphan child rows or the FK add fails.**

### 🐛 Canonical build is itself wrong in one place (migration ≠ model)
- `project (user_id, created_at)` index: the **model** declares `Index('idx_project_user_created',
  user_id, created_at.desc())` (DESC) and **all three live envs have it DESC**, but the **migrations
  build produces it ASC** — a migration created the index without `.desc()`. So a fresh from-migrations
  build does NOT match any live env here. reconcile_f must recreate it DESC (fix is in the migration
  layer; live is already correct).

### ❓ OPEN DECISIONS — must be answered before reconcile_f is written
- **supplier_quote(_item).session_id cascade:** model says plain, prod/otn have `ON DELETE CASCADE`.
  Either (i) add `ondelete='CASCADE'` to the model + a migration (cascade is arguably the *right*
  behaviour — deleting a session should remove its quotes), or (ii) strip CASCADE from prod/otn to
  match the model. Pick one.
- **Legacy `idx_*` duplicates:** `idx_cable_project`, `idx_takeoff_room_project`, `idx_detection_room`
  (present in mig+prod, absent staging+otn) **plus** 5 fully-consistent `idx_*`/`ix_*` pairs present
  identically in all four (`invoice.document_type`, `invoice.job_reference`, `invoice_item.part_number`,
  `part_number_correction.supplier_name`, `project_material.part_number`). Recommend **drop** the
  redundant `idx_*` everywhere (and from the migration that creates them) — but confirm.
- **`customer_invoice_line` index canonical name:** `ix_customer_invoice_line_invoice_id` (prod/otn/mig)
  vs staging's `ix_customer_invoice_line_customer_invoice_id`. Pick one; rename the other (pure
  rename, no data risk).

### Perf-index presence gaps (create-if-absent, no correctness risk)
- staging missing: `customer_invoice(view_token)` plain, `supplier_account(supplier_name)`, both
  takeoff indexes, the 3 legacy `idx_*`.
- otn missing: `takeoff_symbol_detection(project_id,symbol_type_id)`, `takeoff_symbol_template(project_id)`,
  the 3 legacy `idx_*`.

### Gate
**reconcile_f is a fresh-session build** after the 3 open decisions are made. After it ships, re-run
`scripts/index_divergence_audit.sh` and require **0 diffs across all four schemas** before `create_all`
+ the inline ALTERs are removed.

## Verification tooling (in repo)
- `scripts/index_divergence_audit.sh` — **THE gate-check** for the removal session: read-only index +
  constraint + nullability diff across the canonical build and all three live DBs (needs `PROD_URL`,
  `STAGING_URL`, `OTN_URL` public URLs; queries live catalogs directly, no row data). Must show 0
  diffs across all four before `create_all` comes out.
- `scripts/rebuild_from_migrations_test.sh` — from-empty migrations build vs a prod snapshot (diff).
- `scripts/reconcile_e_verify.sh` — build (D+E) vs prod-copy-advanced-to-E (apples-to-apples) +
  E's exact effect on a prod copy.
- `scripts/reconcile_d_idempotency_test.sh` — no-op proof on a prod copy.
- `scripts/reconcile_d_fix_verify.sh` — cross-env proof of the reconcile_d NOT-NULL fix.

## Standing gate
`create_all` + the 3 inline ALTERs in `app/__init__.py` remain **untouched**. Their removal is a
separate, later, explicitly-gated session — and is blocked on the divergence above being resolved.
