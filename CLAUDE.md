# CLAUDE.md — GoZappify (invoice-processor-saas)

## What this project is

GoZappify (gozappify.com) is a SaaS platform for UK trades and contractors. It uses AI to
process supplier invoices, apply markup, and sync to QuickBooks Online or Xero — or send
invoices directly to customers. Built and run by a solo founder who is also a working
electrician in Jersey, Channel Islands. Accuracy of invoice extraction IS the product;
treat anything touching extraction, validation, or money maths as critical-path code.

## Stack

- **Backend:** Python / Flask
- **Database:** PostgreSQL
- **Hosting:** Railway. Two environments, both live (as of 2026-06-15): **production**
  auto-deploys from `master`, and **staging** auto-deploys from the `staging` branch
  (separate Railway service + its own PostgreSQL database). The staging-first workflow below
  is now fully operational — verify changes on staging before merging to production.
- **Integrations:** QuickBooks Online, Xero, Gmail OAuth, IMAP email ingestion, PayPal
  subscriptions (incl. annual tiers), Telegram alerts, reCAPTCHA v3
- **AI:** Anthropic API for invoice/quote parsing. NOTE (2026-06 audit): calls do NOT yet use
  schema-enforced structured outputs — they parse free-text JSON, and model names are hardcoded
  at 11+ call sites (AUDIT.md §3.5). One OpenAI call exists: `app/services/description_cleaner.py`
  (`gpt-4o-mini`). Centralised model config + structured outputs are the target state, not the
  current state.
- **Repo:** github.com/IncognitoJsy/invoice-processor-saas

### Verified commands (2026-06-11)

- Tests: `python -m pytest tests/` (root-level `test_basic.py`/`test_pdf.py` are scratch
  scripts, not part of the suite)
- Server (production): `gunicorn wsgi:app` — Procfile runs `flask db upgrade` first; Railway
  builds from the Dockerfile. Procfile `worker:`/`beat:` lines reference `app.celery`, which
  does not exist — ignore them.
- Migrations: Alembic via Flask-Migrate (`flask db upgrade`). Beware: `app/__init__.py` also
  runs `db.create_all()` + inline ALTERs at startup, so schema is managed in two places
  (AUDIT.md risk #10).

## How I work — follow these rules

1. **Phased builds with verification.** Break work into phases. After each phase, run/verify
   before moving on. Never deliver a big-bang change across many files without checkpoints.
2. **Complete files over diffs** when presenting code for review outside the editor.
   Inside Claude Code, normal edits are fine — but summarise exactly which files changed.
3. **Never push to production directly.** Workflow is: feature branch → `staging`
   branch → verify on Railway staging → merge to `master` for production. Always stop and ask
   before anything that deploys to production. As of 2026-06-15 the Railway staging environment
   is live (auto-deploys from `staging`), so this gate is now real — push to `staging`, verify
   the changed flows on the staging deploy, and only then merge to `master`.
4. **Don't delete features — flag them.** A feature-flag system exists (used to hide
   Voice to Quote and Quote Builder). When asked to remove/hide a feature, default to
   flagging it off, not deleting code, unless explicitly told to delete.
5. **Ask before destructive operations:** DB migrations that drop/alter columns, deleting
   webhook configs, changing OAuth scopes, touching PayPal billing logic.

## Critical-path areas (extra care required)

- `invoice_validator.py` — arithmetic validation + cross-parser verification. Any change
  here needs test cases covering: line-item totals vs invoice total, VAT calculations,
  discounts, multi-page invoices, and the known cross-parser verification gap fix.
  **AUDIT FINDING (2026-06): the validator is currently NOT called anywhere in the live
  pipeline** — `save_invoice_to_db()` stores AI output unvalidated (AUDIT.md risk #1).
  Wiring it in is the top open fix; remove this note once done.
- **Markup logic** — errors here directly cost users money. Test with edge cases
  (zero-value lines, credits/refunds, mixed VAT rates). **Retail cap (2026-06-23, branch
  `fix-retail-price-cap`):** per-unit selling is capped at the supplier list price
  (`original_unit_price`), applied AFTER the markup band AND the QB-price override — retail is the
  absolute ceiling, the structural guarantee that selling never exceeds counter price (the bands
  alone can't, e.g. a band-edge `0.69×1.50=1.035`). No-ops on missing retail / per-metre-converted
  lines / retail≤cost (flags instead). On the registered path it binds at band edges (the
  unregistered GST-fold overage is gone). See AUDIT.md §2 / AUDIT_FINDINGS.md; tests
  `test_claude_parser_calc.py::test_retail_cap_*`.
- **QuickBooks / Xero sync** — two-way customer sync design exists. Watch for duplicate
  creation, ID mapping, and token refresh handling.
- **Compliance features** — VAT settings, VOID invoices, supply date. UK invoicing rules
  apply; don't simplify these away.
- **Secrets** — all credentials live in Railway environment variables. Never hardcode,
  never log tokens, never commit .env files.

## Known context / open work

- **DONE (2026-06-15) — real staging environment is live.** A second Railway environment
  (separate service + its own PostgreSQL database) now auto-deploys from the `staging` branch,
  so changes can be verified against a production-like setup before reaching `master`/production.
  This unblocked the Sprint A fixes — including the **Float→Decimal money migration**
  (AUDIT.md risk #4), which alters live financial data.
- **DONE (2026-06-23) — vat_*→tax_* unification + Settings tax-registration UI** (branch
  `fix-settings-tax-registered`; suite 196). Fixes two post-go-live bugs (Settings "VAT Registered"
  toggle flipped off on save; picked GST showed/synced 0%). Root cause: two parallel flag sets and
  the Settings page only exposed the legacy `vat_registered` (which `update_profile` never saved),
  so `tax_registered` — the flag `effective_output_rate`/resolver/parser actually use — had no
  working UI. New `POST /settings/tax` form persists `tax_registered`/`tax_type`/`tax_number`;
  **tax_rate stays owned by the picker when connected** (handler must not zero it), manual+guard when
  not. Migrated the 3 `vat_*` readers (`reports.py /api/vat` gate + box4, `reports/index.html`,
  `customer_invoices/preview.html`) to `tax_*`; `vat_*` columns kept (no drop), `/api/vat`-vs-
  `tax_reports.py` redundancy flagged for separate cleanup. `picked_but_not_registered` warning
  (distinct from `output_rate_unconfigured`); `tax_noun` GST/VAT label (Jersey→GST).
  - **🚨 RELEASE NOTE — changes live financial behaviour:** switching `tax_registered=True` flips the
    **parser cost-base** (`claude_parser.py:1139`) — unregistered fold irrecoverable input GST into
    the markup base; registered reclaim it (cost ex-tax). Correct for Proton.je, but **cost/markup/
    selling on future imports changes** the moment an account becomes registered. Pinned by
    `test_claude_parser_calc.py::test_cost_base_*`. (Same prominence as the picker re-pick note.)
- **DONE (2026-06-23) — output tax-code PICKER** (branch `sprint-a-phase2-markup`,
  `126898e`→`fab37b0`; full suite 174). Registered users pick their output sales tax code **once**
  from a read-only dropdown sourced from their connected software (`GET /settings/tax-codes`);
  it's stored on `User` (`output_tax_code_ref`/`_name`/`_provider`; `tax_rate` snapshotted from the
  code at pick, re-validated server-side on save). The QB/Xero resolver attaches the **picked ref
  directly — no per-sync `TaxRate` read, no rate-match** (this **supersedes** the 2c/3c match-or-fail;
  `_select_taxable_code`/`_select_taxable_tax_type` deleted, rate-discovery helpers kept for the
  picker only, and the `814f7b8` retry+cache follow-up in `AUDIT_FINDINGS.md` is now **superseded**).
  Provider-guarded; unregistered still exempt.
  - **🚨 RELEASE NOTE (read before deploy):** existing **GST/VAT-registered users with QuickBooks or
    Xero connected — including our own Proton.je — must open Settings → "Output tax code" and pick
    once after this ships, or their syncs fail closed.** Safe regression: it **blocks**
    (`TAX_CODE_UNRESOLVED`), never mis-rates / never silently syncs tax-free. The amber Settings
    prompt surfaces it. For Proton.je: **fold this into the go-live config step** (pick GST id 2 once).
  - Sync block states: `TAX_CODE_UNRESOLVED` (no pick / transient empty list) + the new
    `TAX_CODE_INVALID` (picked code gone from a non-empty live list → "re-pick"; transient/empty list
    stays `UNRESOLVED`). Disconnect clears the pick. **A2 edge (documented, not built):** picked rate
    is a snapshot — if the provider changes the rate behind the same code id, document vs sync
    diverge until re-pick; periodic re-validation is a later option. See AUDIT.md §2 / AUDIT_FINDINGS.md.
- **DONE (2026-06-18) — Sprint A Phase 2** (branch `sprint-a-phase2-markup`; per-line diagnosis
  in `AUDIT_FINDINGS.md`; full suite 147 passed). Closed:
  - **AUDIT risk #4 — Float→Decimal money: ✅ CLOSED on the rounding/Decimal axis (both halves).**
    Phase 1 (2026-06-15) migrated the 28 Float money columns to Numeric; Phase 2 (`fce9fd6`)
    added the shared Decimal `money()` helper (`app/utils/money.py`, also used by
    `invoice_validator`) and Decimalised the **supplier-invoice + QB/Xero sync** path (parser →
    markup → `save_invoice_to_db` → sync payloads); Phase 2b (`ec98ba7`, diagnosis `d37f77b`)
    Decimalised the **customer-document + report** path (`customer_invoice`/`customer_quote`
    recalc + `calculate_total`, `job_cards` recalc/merge, `customer_invoices.py`
    line/merge/summary/manual, and `tax_reports.py` + `reports.py` P&L/VAT boxes). All live money
    arithmetic is now Decimal, ROUND_HALF_UP, line-authority, with float only at the
    DB/JSON/CSV/API edges; also fixed 3 reachable `Decimal+float` merge crashes. See AUDIT.md §2.
  - **Step 2c — ✅ DONE** (`7a7c284` document side, `87ac248` resolver side): the printed
    customer-document tax line and the QB/Xero resolver both derive from one shared
    `effective_output_rate(user)` = (registered ? tax_rate : 0) (`app/utils/tax.py`). Documents
    snapshot it at create and never re-derive (immutable records); the resolver targets it with
    **match-or-fail** (the matched code's real rate must equal the configured rate, else fail
    closed — 3c's single-code/keyword/country fallbacks removed); registered-but-rate-unset is
    blocked at document create, sync, and settings save. Production-verified read-only
    (`scripts/check_output_tax.py`): registered → `(GST id 2, taxable)` at real 5%, unregistered →
    exempt; no QBO writes. Residual edge (rare, documented): a PDF + a separately-synced supplier
    invoice for one job can differ if the rate changes between — resolver fail-closed protects books.
    ⚠️ **DEFERRED money path — Quote Builder:** `project.py` contingency + `project_material`/
    `project_labour` maths are still float/unrounded. Quote Builder is flagged OFF so it isn't
    live, but this **must be migrated to `money()` before the flag is turned on / Quote Builder
    goes public** (AUDIT.md §2.3).
  - **Markup** (`7da148b`): per-unit price-override no longer multiplies a line total by quantity
    (the qty² overcharge); markup tier bands made continuous (no fractional-discount gap);
    `avg_markup` cap kept in Decimal (F1).
  - **Part-number OCR** (`0b3c7d5`): matcher no longer conflates distinct parts on a
    digit-for-digit difference (SB20MWH↔SB25MWH); printed code wins unless glyph misread /
    learned / exact match.
  - **QuickBooks & Xero output GST** (`b357f33` QB, `cd54ffc` Xero): registration- & region-aware
    — unregistered → tax-exempt, registered → rate-matched code/TaxType (Jersey 5% over UK 20%),
    no resolvable code → fail closed (`TAX_CODE_UNRESOLVED`) instead of silently syncing tax-free.
  - **QB resolver hardened (Step 3c)** (`16edb91`): reads each code's real rate from its
    `TaxRateRef` detail (not the name) + single-code fallback; drops the UK-20%/address-country
    default. Fixes the live GST-only company whose sole code is named just `"GST"` (5% in the
    detail) — previously fail-closed the registered path. Verified read-only against production
    via `scripts/check_output_tax.py` (`3b7071b`): registered → `(GST id 2, taxable)` at 5%.
  - **Cleanup** (`fbee76a`): deleted the dead duplicate `app/services/quickbooks_service.py`.
- Feature flags shipped to `staging`; production rollout pending verification.
- QuickBooks App Store submission: submitted, review call requested — avoid breaking
  anything the QB review might exercise (OAuth flow, disconnect flow, sync accuracy).
- Planned: employee-facing timesheet PWA with passkey/biometric login.
- Planned: two-way QuickBooks customer sync (architecture already designed — find the
  design notes before implementing).
- Known issue: homepage pricing inconsistencies across tiers — pinned down by the 2026-06
  audit (AUDIT.md §8.3): landing page sells a £49/£529 "Full Platform" tier that has no
  PayPal plan (actual `full-starter` is £39/£429), and mis-scoped `ENABLE_VOICE_TO_QUOTE`
  blocks render the first two pricing cards with empty feature lists when the flag is off.
- Phase 1 audit complete: see AUDIT.md (2026-06-11) for the full findings and Top 10 risks.
- Labour & Employees module uses Jersey social security defaults.

## Product roadmap context (for design decisions)

When building, keep these strategic directions in mind — prefer implementations that
don't paint us into a corner on:

1. **Price-creep intelligence** — per-SKU, per-supplier price tracking across historical
   invoices with margin-erosion alerts. Schema/DB decisions should preserve normalised
   line-item history (SKU/description, unit price, supplier, date) to make this possible.
2. **Voice to Quote revival** — currently flagged off. Improvements to structured-output
   parsing may make it viable again; keep its code paths healthy.
3. **Conversational queries over user data** — natural-language questions about spend,
   margins, suppliers. Favour clean queryable schemas over blobs.
4. **Model routing** — cheap/fast model (Haiku/Sonnet) for routine extraction, escalate
   to a frontier model only when the validator flags a discrepancy or confidence is low.
   Keep model name/config centralised, never scattered through the codebase.

## Conventions

- Python: clear over clever; type hints on new code; docstrings on anything non-obvious.
- Target: all AI parsing calls should use schema-enforced structured outputs. (Not yet true —
  see AUDIT.md §3.5. Any new AI call must use structured outputs; migrate existing ones as touched.)
- Telegram-style operational alerts and logging patterns are familiar territory; reuse
  existing notification patterns rather than inventing new ones.
- Currency: GBP throughout. Jersey context: no VAT locally but UK customers have VAT —
  never assume one tax regime.
- Timezone: Europe/London (Jersey follows UK time).

## Deployment

- Railway auto-deploys **production from `master`** and **staging from `staging`** — two
  separate services, each with its own PostgreSQL database (both live as of 2026-06-15).
- Before any merge toward production: run the test suite, confirm with me, and manually
  verify the changed flows on the staging deploy first (the intended gate, now real).

## Testing

- Run the existing test suite before and after changes: `python -m pytest tests/`
  (currently 18 tests, all for `invoice_validator.py`). If a critical-path module has no
  tests, write them as part of the change — per the audit, parsers, markup, sync, and
  billing currently have NONE (AUDIT.md §4).
- For extraction/validation changes: there are NO sample-invoice fixtures in the repo
  (gap confirmed by 2026-06 audit). Building the fixture corpus is a LAUNCH.md §0 item;
  until it exists, flag this on every extraction change.
