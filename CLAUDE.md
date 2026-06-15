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
  (zero-value lines, credits/refunds, mixed VAT rates).
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
- **AUDIT risk #4 — Float→Decimal money: Phase 1 ✅ DONE, Phase 2 ⏳ OUTSTANDING.**
  Phase 1 (2026-06-15) migrated all 28 Float money columns to Numeric in production
  (`money_float_to_numeric`) — storage-only and behaviour-preserving (verified: checksum
  and row counts unchanged). **Phase 2 is still to do and risk #4 is NOT closed until it
  lands:** add the shared Decimal `money()` helper (the validator already has one) and
  convert every float `round()` calculation/sync site to round-per-line-then-sum in Decimal,
  plus build the missing money test corpus (markup, mixed VAT, discounts, credits, VAT
  report, QB/Xero sync). Until then, storage is Numeric but the live arithmetic is still
  binary float + banker's rounding. See AUDIT.md §2 and risk #4.
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
