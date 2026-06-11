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
- **Hosting:** Railway (staging + production environments)
- **Integrations:** QuickBooks Online, Xero, Gmail OAuth, PayPal subscriptions (incl. annual tiers)
- **AI:** Anthropic API for invoice/quote parsing with schema-enforced structured outputs
- **Repo:** github.com/IncognitoJsy/invoice-processor-saas

> NOTE: Verify exact commands (run server, run tests, migrations) against the repo on
> first session and update this file. Do not guess at commands.

## How I work — follow these rules

1. **Phased builds with verification.** Break work into phases. After each phase, run/verify
   before moving on. Never deliver a big-bang change across many files without checkpoints.
2. **Complete files over diffs** when presenting code for review outside the editor.
   Inside Claude Code, normal edits are fine — but summarise exactly which files changed.
3. **Never push to production directly.** Workflow is: feature branch → `staging` branch →
   verify on Railway staging → merge to production. Always stop and ask before anything
   that deploys to production.
4. **Don't delete features — flag them.** A feature-flag system exists (used to hide
   Voice to Quote and Quote Builder). When asked to remove/hide a feature, default to
   flagging it off, not deleting code, unless explicitly told to delete.
5. **Ask before destructive operations:** DB migrations that drop/alter columns, deleting
   webhook configs, changing OAuth scopes, touching PayPal billing logic.

## Critical-path areas (extra care required)

- `invoice_validator.py` — arithmetic validation + cross-parser verification. Any change
  here needs test cases covering: line-item totals vs invoice total, VAT calculations,
  discounts, multi-page invoices, and the known cross-parser verification gap fix.
- **Markup logic** — errors here directly cost users money. Test with edge cases
  (zero-value lines, credits/refunds, mixed VAT rates).
- **QuickBooks / Xero sync** — two-way customer sync design exists. Watch for duplicate
  creation, ID mapping, and token refresh handling.
- **Compliance features** — VAT settings, VOID invoices, supply date. UK invoicing rules
  apply; don't simplify these away.
- **Secrets** — all credentials live in Railway environment variables. Never hardcode,
  never log tokens, never commit .env files.

## Known context / open work

- Feature flags shipped to `staging`; production rollout pending verification.
- QuickBooks App Store submission: submitted, review call requested — avoid breaking
  anything the QB review might exercise (OAuth flow, disconnect flow, sync accuracy).
- Planned: employee-facing timesheet PWA with passkey/biometric login.
- Planned: two-way QuickBooks customer sync (architecture already designed — find the
  design notes before implementing).
- Known issue: homepage pricing inconsistencies across tiers (audit flagged this).
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
- All AI parsing calls use schema-enforced structured outputs — keep it that way.
- Telegram-style operational alerts and logging patterns are familiar territory; reuse
  existing notification patterns rather than inventing new ones.
- Currency: GBP throughout. Jersey context: no VAT locally but UK customers have VAT —
  never assume one tax regime.
- Timezone: Europe/London (Jersey follows UK time).

## Deployment

- Railway auto-deploys from connected branches. `staging` branch → staging environment.
- Before any merge toward production: run the test suite, manually verify the changed
  flows on staging, then confirm with me.

## Testing

- Run the existing test suite before and after changes (check repo for exact command —
  likely `pytest`). If a critical-path module has no tests, write them as part of the change.
- For extraction/validation changes: test against real sample invoices in the repo's
  test fixtures if present; if not present, flag this gap.
