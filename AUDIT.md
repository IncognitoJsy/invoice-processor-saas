# GoZappify — Phase 1 Codebase Audit

Date: 2026-06-11 · Branch audited: `staging` (commit `bd58d5c`) · Read-only audit, no code changed.

This document follows the eight sections of the Phase 1 audit prompt and ends with a ranked
Top 10 risk table. File references are `path:line` against the audited commit. High-impact
claims (validator wiring, duplicate columns, IDOR, webhook verification, fail-open cron,
celery references) were independently re-verified, not just pattern-matched.

---

## STATUS UPDATE (2026-06-18) — Sprint A Phase 2 fixes landed

Branch `sprint-a-phase2-markup`; per-line diagnosis preserved in `AUDIT_FINDINGS.md`. The items
below are now **CLOSED** (sections further down carry inline ✅ markers). Full suite: **143 passed**.

- **Risk #4 — money maths: ✅ CLOSED for the supplier-invoice + sync path; ⏳ customer-facing
  path still open.** Phase 1 (Float→Numeric storage, 2026-06-15, all 28 columns) + Phase 2
  (`fce9fd6`): a single shared Decimal `money()` helper (`app/utils/money.py`, also adopted by
  `invoice_validator`). All money arithmetic on the **supplier-invoice extraction → markup →
  storage path and the QB/Xero sync path** is now Decimal, with float only at the DB / JSON
  response / QB+Xero API edges; invoice totals are line-authority and reconcile to the penny
  (`total_profit == total_selling − total_cost`); ROUND_HALF_UP throughout. Money test corpus
  added (`tests/unit/test_money.py`, `tests/unit/test_claude_parser_calc.py`,
  `tests/integration/test_money_totals.py`).
  **Still float `round()` (NOT in this sprint):** the full-platform customer-document maths —
  `customer_invoice.recalculate_totals()`, `customer_quote`, `customer_invoices.py` line/summary,
  `job_cards.py` invoice lines/tax, and the P&L / VAT-return reports (`reports.py`,
  `tax_reports.py`). Storage is Numeric there (Phase 1) but the arithmetic is still binary float —
  these inherit `money()` next.
- **Markup — ✅** per-unit price-override no longer multiplies a line total by quantity (the
  qty² overcharge), markup tier bands made continuous (no fractional-discount gap), `avg_markup`
  cap kept in Decimal (F1) — `7da148b`.
- **Part-number OCR — ✅** matcher no longer conflates distinct parts on a digit-for-digit
  difference (SB20MWH↔SB25MWH); the printed code wins unless it's a glyph misread or a
  learned/exact match — `0b3c7d5`.
- **QuickBooks & Xero output GST — ✅** registration- & region-aware: unregistered → tax-exempt,
  registered → the rate-matched code/TaxType (Jersey 5% over UK 20%), and a registered user with
  no resolvable code **fails closed** (`TAX_CODE_UNRESOLVED`) instead of silently syncing
  tax-free — `b357f33` (QB), `cd54ffc` (Xero).
- **QB resolver hardened against real tax-code shapes (Step 3c) — ✅** `16edb91`. Reads each
  code's ACTUAL rate from its `TaxRateRef → TaxRate.RateValue` (stops parsing the rate from the
  name); adds a single-code fallback (one active non-exempt sales code → use it); drops the
  UK-20% / address-country default that fail-closed the live GST-only company (Proton.je, sole
  code named just `"GST"`, 5% in the detail). Verified read-only against production: registered →
  `(GST id 2, taxable)` at a real 5%, unregistered → exempt.
- **Dead duplicate `app/services/quickbooks_service.py` deleted** — `fbee76a`.
- **Parser-calc regression suite added** — `9aa9aa0`. Read-only QBO diagnostic
  `scripts/check_output_tax.py` — `3b7071b`.

---

## 1. Codebase map

### 1.1 Structure

```
app/
├── __init__.py          # App factory: flags, blueprints, CSRF exemptions, subscription wall,
│                        #   security headers, health check, landing route
├── config.py            # Config classes (dev/prod/test) — env-driven
├── extensions.py        # db, migrate, login_manager, limiter (Flask-Limiter), csrf (Flask-WTF)
├── web/                 # 30 blueprints (routes)
│   ├── auth/routes.py   # register/login/logout/password reset
│   ├── billing.py       # PayPal subscriptions, top-ups, webhook
│   ├── upload.py        # manual invoice upload → parse → save
│   ├── queue.py         # email-fetched invoice queue → parse → save
│   ├── invoices.py, bills.py, customers.py, customer_invoices.py, customer_quotes.py,
│   │   customer_payments.py, job_cards.py, employees.py, products.py, quotes.py,
│   │   supplier_quotes.py, reports.py, tax_reports.py, dashboard.py, settings.py,
│   │   setup.py, integrations.py (QB/Xero OAuth + sync), gmail_auth.py, imap_auth.py,
│   │   user_api.py, part_number_routes.py, pages.py, errors.py, tasks.py (cron endpoints),
│   │   voice_to_quote.py (flagged off), quotebuilder.py (flagged off)
├── parsers/             # claude_parser.py (main AI extraction), parser_service.py (orchestrator),
│                        #   cef_parser.py, yesss_parser.py, wholesale_parser.py (regex parsers),
│                        #   drawing_parser.py, base_parser.py, upload_fixed.py (dead),
│                        #   parser_service.py.backup, yesss_parser.py.backup (dead)
├── services/            # invoice_validator.py (NOT WIRED IN — see §3), invoice_processor.py,
│                        #   email_fetcher.py, gmail_service.py, imap_fetcher.py, paypal_service.py,
│                        #   pdf_generator.py, pdf_service.py (dead), product_matcher.py,
│                        #   duplicate_detection.py, description_cleaner.py (OpenAI!),
│                        #   email_sender.py + email_service.py (overlapping),
│                        #   symbol_detector.py + symbol_detector_ai.py (overlapping)
│                        #   [quickbooks_service.py stale duplicate — DELETED fbee76a]
├── integrations/        # quickbooks_service.py (the imported copy), xero_service.py
├── models/              # 22 model modules (see §7)
├── utils/               # password_validation.py, upload_validation.py
├── tasks/, api/         # empty packages (only __init__.py)
└── templates/           # 27 template directories, ~73 HTML files
migrations/versions/     # 34 Alembic migrations (incl. merge_heads_001.py)
tests/unit/              # test_invoice_validator.py — the ONLY real test module
test_basic.py, test_pdf.py  # root-level scratch scripts, not part of the suite
```

**Run/deploy commands (verified):**
- Tests: `python -m pytest tests/` (18 tests, pass)
- Server: `gunicorn wsgi:app` (Procfile runs `flask db upgrade` first); Railway builds from Dockerfile
- Procfile `worker:`/`beat:` lines reference `app.celery` which **does not exist** — dead config

### 1.2 App factory notes (`app/__init__.py`)

- Feature flags `ENABLE_VOICE_TO_QUOTE` / `ENABLE_QUOTE_BUILDER` read from env, default **off** (lines 16–19).
- `db.create_all()` runs at startup plus inline `ALTER TABLE` statements (lines 35–76) — schema
  drift happens outside Alembic; the migration history no longer fully describes production schema.
- **CSRF is exempted for 22 of ~30 blueprints** (lines 84–100, 268–282), including `billing`,
  `invoices`, `customers`, `customer_invoices`, `products`, `employees`, `reports`. Mitigated in
  practice by `SESSION_COOKIE_SAMESITE='Lax'`, but the exemption list deserves a comment and audit.
- Subscription wall `before_request` (lines 118–186) gates expired/cancelled users; its
  `allowed_endpoints` set references endpoints that don't exist (`billing.paypal_webhook`,
  `billing.check_subscription` — actual endpoints are `billing.webhook`, `billing.api_status`).
  Harmless but stale.
- Security headers + CSP registered globally (lines 288–341); HTTPS redirect in production.

### 1.3 CLAUDE.md corrections found

| CLAUDE.md said | Reality |
|---|---|
| "Verify exact commands … likely `pytest`" | Confirmed: `python -m pytest tests/`. Root `test_basic.py`/`test_pdf.py` are scratch scripts. |
| "All AI parsing calls use schema-enforced structured outputs" | **False.** No AI call uses structured outputs/tool-schema enforcement; all parse free-text JSON, several via regex (§3.5). |
| "`invoice_validator.py` — arithmetic validation + cross-parser verification" | Module exists and is tested, but **is not called anywhere in the live pipeline** (§3.2). |
| AI = "Anthropic API" | Mostly, but `app/services/description_cleaner.py` calls **OpenAI** (`gpt-4o-mini`); `OPENAI_API_KEY` is in config. |
| Stack lists QuickBooks/Xero/Gmail/PayPal | Also present: IMAP email ingestion, Telegram alerts, reCAPTCHA v3, Redis (rate limiting). |

(CLAUDE.md has been updated alongside this audit.)

---

## 2. Money-maths inventory

Full sweep of every currency calculation. Verdict up front: **inconsistent and fragile** —
three different numeric regimes coexist (Decimal+ROUND_HALF_UP in the unused validator,
binary floats + Python `round()` (banker's rounding) in most live code, and Numeric columns
in some tables vs Float in others).

### 2.1 Storage types

**UPDATE (2026-06-18) — storage fully Numeric; arithmetic now Decimal on the supplier path.**
Phase 1 (2026-06-15) migrated all 28 Float money columns to Numeric in production via
`money_float_to_numeric` (storage-only, behaviour-preserving: verified checksum unchanged, row
counts intact) — the rows below that previously read **Float** are now Numeric ✅. Phase 2
(`fce9fd6`, 2026-06-18) replaced float arithmetic with the shared Decimal `money()` helper on the
**supplier-invoice + QB/Xero sync path** (§2.2 rows marked ✅). The customer-facing/full-platform
calculation sites in §2.2 (storage already Numeric) still use float `round()` — see §2.3.

| Table / columns | Type |
|---|---|
| `invoice.total_cost/total_selling/total_profit/average_markup` | Numeric ✓ |
| `invoice.supplier_tax_amount/supplier_tax_rate/total_ex_tax/total_inc_tax` | Numeric ✅ (was Float, Phase 1) |
| `invoice_item.*` (cost, selling, profit, markup) | Numeric(10,4)/(10,2) ✓ |
| `customer_invoice.subtotal/tax_rate/tax_amount/total` + line `quantity/unit_price/line_total` | Numeric ✅ (was Float, Phase 1) |
| `customer_quote.*` + lines | Numeric ✅ (was Float, Phase 1) |
| `customer_payment.amount`, `customer_invoice_payment.amount_applied` | Numeric ✅ (was Float, Phase 1) |
| `project`, `project_material`, `project_labour`, `supplier_quote_item`, `product`, `employee` | Numeric ✓ |
| `user.default_markup`, `user.tax_rate`, `product_service.*`, `product_cache.*` | Numeric ✅ (was Float, Phase 1) |

The **customer-facing invoice path — the documents users actually send for money — is entirely
Float**, while the supplier-invoice path is mostly Numeric. VAT amounts on both sides
(`invoice.supplier_tax_amount`, `customer_invoice.tax_amount`) are Float, and the VAT return
report sums them (`tax_reports.py:78,90–94`).

### 2.2 Calculation sites (selected; full list of defects)

| Location | Calculation | Type / rounding issue |
|---|---|---|
| `parsers/claude_parser.py` `_transform_items` | discount + markup (`cost × (1+markup)`) | ✅ Decimal + `money()` (`fce9fd6`). NOTE: `yesss_parser.py`/`wholesale_parser.py` regex parsers still float `round()` |
| `web/upload.py` `save_invoice_to_db` totals | totals from items | ✅ Decimal, line-authority, `money()` (`fce9fd6`) |
| `web/upload.py` average markup | average markup | ✅ Decimal cap + `money()` (F1, `7da148b`/`fce9fd6`) |
| `web/upload.py` tax columns | supplier tax / ex-/inc-tax write | ✅ `money()` (F4, `fce9fd6`) — was raw `float()` into Numeric |
| `models/customer_invoice.py:61–65` | `recalculate_totals()` | ⏳ still float, `round()` (full-platform path, not this sprint) |
| `models/customer_quote.py:39–42`, line `:81–82` | quote totals | float, `round()` |
| `web/customer_invoices.py:249–281` | line merge/summary lines | float, `round()` |
| `web/job_cards.py:375,385` | merged/new invoice lines | float, **no rounding at all** |
| `web/job_cards.py:429–432` | `_recalculate_invoice()` tax | **tax never rounded** before storage |
| `models/project.py:83` | contingency amount | no rounding |
| `web/reports.py:87–117,171–173` | P&L + VAT estimate | float aggregation, rounding only at output |
| `web/tax_reports.py:78–108` | VAT return sums | sums Float columns, output rounding only |
| `integrations/quickbooks_service.py` payloads | QB prices/line amounts | ✅ `float(money(...))` at payload edge (`fce9fd6`); GST tax code registration/region-aware (`b357f33`), hardened to read the real `TaxRateRef` rate + single-code fallback (`16edb91`) |
| `integrations/xero_service.py` payloads | price comparison + line amounts | ✅ Decimal rate compare + `float(money(...))` UnitAmount (`cd54ffc`/`fce9fd6`) |
| `services/invoice_validator.py` | `_to_decimal()`/`_money()` | ✅ now delegate to the shared `app/utils/money.py` helper (`fce9fd6`) — one rounding implementation |
| `web/billing.py:11,270` | top-up amount | float (`0.50 × qty`) — exact in practice for .50 steps |

### 2.3 Consistency verdict

- **Rounding strategy differs by stage**: validator uses ROUND_HALF_UP; live code uses Python
  `round()` (round-half-to-even); job-card invoice maths and project contingency don't round at all.
- **Per-line vs total divergence is possible**: lines are rounded individually in some paths
  (`customer_invoices.py`) and not in others (`job_cards.py`), then totals are recomputed from
  lines — penny-level drift on larger invoices is expected, and the unrounded job-card tax can
  store values like `24.59999999` in a Float column.
- **Tests**: only the (unused) validator's Decimal maths is tested. **Zero tests** cover markup,
  customer invoice totals, VAT reports, or sync amounts.

Fix direction: migrate Float money columns to Numeric, do all arithmetic in Decimal with one
shared `money()` quantize helper (the validator already has it), round per line then sum.

**Progress:**
- **Phase 1 ✅ DONE (storage, 2026-06-15):** all 28 Float money columns migrated to Numeric in
  production (`money_float_to_numeric`); behaviour-preserving, verified (checksum + row
  counts unchanged). Scales: prices `Numeric(10,4)`, quantities `Numeric(10,3)`, line/tax
  amounts `Numeric(10,2)`, document totals/payments `Numeric(12,2)`, rates `Numeric(5,2)`.
- **Phase 2 ✅ DONE for the supplier-invoice + sync path (`fce9fd6`, 2026-06-18):** shared
  Decimal `money()` helper (`app/utils/money.py`); `claude_parser`, `save_invoice_to_db`,
  `quickbooks_service`, `xero_service`, `invoice_validator`, and `Invoice.to_dict` all Decimal
  with float only at DB/JSON/API edges; round-per-line, line-authority totals reconcile to the
  penny; ROUND_HALF_UP. Test corpus added (markup tiers, mixed VAT, discount round-half-up,
  per-unit penny, QB/Xero sync, totals reconciliation).
- **Phase 2 ⏳ REMAINING — full-platform customer-document path:** `customer_invoice`/
  `customer_quote` totals, `customer_invoices.py` line/summary maths, `job_cards.py` invoice
  lines + tax, and the P&L / VAT-return reports (`reports.py`, `tax_reports.py`) still use float
  `round()` (storage is Numeric, arithmetic is not). These inherit the same `money()` helper next;
  until then customer-facing documents and VAT returns can still carry penny drift.

---

## 3. Extraction pipeline review

### 3.1 Pipeline trace

1. **Entry — manual upload**: `app/web/upload.py:89` `api_upload_single()` → MIME/magic-byte/size
   checks via `validate_upload()` (`upload.py:119`) → `InvoiceParserService.parse()` (`upload.py:127–154`).
2. **Entry — email**: `app/services/email_fetcher.py:455` `fetch_emails_for_user()` → Gmail
   (`:224`) / IMAP (`:379`) → PDFs deduplicated by message-id + SHA-256 (`:162–174`) → stored as
   `QueuedInvoice` rows (no parsing yet). Parsing happens when the user processes the queue:
   `app/web/queue.py:213` `api_process_from_queue()` → same `InvoiceParserService.parse()`.
3. **Parsing**: `app/parsers/parser_service.py:31` tries supplier-specific regex parsers
   (YESSS/CEF/Wholesale) first, then `app/parsers/claude_parser.py:462` `ClaudeInvoiceParser.parse()` —
   the main AI call (`claude_parser.py:519–539`, hardcoded model, no schema enforcement). Post-parse:
   document-type/credit-note rejection, part-number OCR correction (`claude_parser.py:241`;
   ✅ `0b3c7d5` — no longer rewrites a printed code to a sibling on a digit-for-digit difference),
   duplicate detection (`parser_service.py:104`).
4. **Storage**: `app/web/upload.py:451` `save_invoice_to_db()` sums item totals and writes
   `Invoice` + `InvoiceItem` rows. **No arithmetic validation happens here.**
5. **Sync**: `app/integrations/quickbooks_service.py` / `xero_service.py` create vendors/bills/items
   from the stored rows. **No validation before posting to the accounting system.**

### 3.2 CRITICAL: the validator is dead code in the live path

`app/services/invoice_validator.py` (`validate_invoice()` at `:98`, `validate_parse_result()` at
`:230`) is imported **only** by its own docstring example and `tests/unit/test_invoice_validator.py`.
Neither `upload.py`, `queue.py`, nor `parser_service.py` calls it. Verified by repo-wide search.

Consequence: every extracted invoice — AI or regex parsed — is stored and can be synced to
QuickBooks/Xero with **zero arithmetic checking**. "Accuracy is the product" is currently
unenforced at runtime; the cross-parser verification gap described in CLAUDE.md is still open.
The fix is small: call `validate_parse_result()` in `save_invoice_to_db()` (both entry paths
funnel through it), set `needs_review`/`confidence` from the result, and block sync on errors.

### 3.3 Points where extraction output is trusted without validation

| # | Location | What is trusted |
|---|----------|-----------------|
| A | `app/web/upload.py:194` → `save_invoice_to_db()` | All AI fields stored as-is |
| B | `app/web/upload.py:459–467` | Totals recomputed by summing items, never reconciled against the invoice's stated totals |
| C | `app/web/queue.py:292` | Same as A via the queue path |
| D | `app/parsers/claude_parser.py:545` | Claude JSON — only document-type & account-number format checked |
| E | `app/parsers/yesss_parser.py` / `cef_parser.py` / `wholesale_parser.py` | Regex parser output, no checks |
| F/G | QB/Xero services | Stored rows posted to accounting without re-validation |

### 3.4 invoice_validator.py — what it catches / what slips through

Catches (lines 98–227): empty item list; line `qty × unit ≠ total`; lines don't sum to net;
`net + tax ≠ gross`; tax inconsistent with rate; implausible tax rate (<0 or >30%); gross < net.
Penny-tolerance scaling included. 18 unit tests cover these paths (all pass).

Would slip through even once wired in:
- **Multi-page invoices** — no consolidation logic for page subtotals.
- **Credit notes / negative lines** — negative lines only warn; a credit note mislabelled
  "invoice" by the supplier passes type checks.
- **Mixed VAT rates** — only aggregate rate consistency is checked, not per-line VAT.
- **Discounts** — the `qty × unit × (1 − disc%)` formula is not validated (warn only).
- **Carriage/delivery charges** — no special-casing; a missed carriage line shows up only as a
  generic total mismatch.
- **Zero-value/placeholder lines** — accepted silently.

### 3.5 AI model configuration — scattered and inconsistent

No central config; model names are hardcoded at 11+ call sites:

| File:line | Model | Purpose |
|---|---|---|
| `app/parsers/claude_parser.py:520` | `claude-sonnet-4-5-20250929` | Main invoice extraction (max_tokens 8192) |
| `app/parsers/drawing_parser.py:269` | `claude-sonnet-4-20250514` | Drawing takeoff |
| `app/services/symbol_detector_ai.py:108,253` | `claude-opus-4-6` | Symbol ID (vision) |
| `app/services/symbol_detector.py:190` | `claude-sonnet-4-20250514` | Symbol fallback |
| `app/services/product_matcher.py:300,391` | `claude-sonnet-4-20250514` | Product matching |
| `app/web/voice_to_quote.py:634,909,1056,2457` | `claude-sonnet-4-5-20250929` | VTQ parsing (4 call sites) |
| `app/web/quotebuilder.py:2231,2332` | `claude-sonnet-4-20250514` | Quote generation |
| `app/web/supplier_quotes.py:305,318,379` | `claude-sonnet-4-20250514` | Supplier quote parsing |
| `app/integrations/quickbooks_service.py:998` (+ stale duplicate in services/) | `claude-sonnet-4-20250514` | QB account matching |
| `app/integrations/xero_service.py:1100` | `claude-sonnet-4-20250514` | Xero account matching |
| `app/services/description_cleaner.py:48` | `gpt-4o-mini` (**OpenAI**) | Description cleanup |

**No call uses structured outputs / schema enforcement** (no tool-schema, no JSON schema);
JSON is recovered by stripping markdown fences or regex (`symbol_detector_ai.py:135`,
`voice_to_quote.py:15` `repair_json()`). This contradicts CLAUDE.md and blocks the planned
model-routing roadmap item (cheap model → escalate on validator flag). Centralising model config
is a small, high-leverage prerequisite and pairs naturally with wiring in the validator.

---

## 4. Test coverage

### 4.1 Suite result

`python -m pytest tests/` → **18 passed in 0.04s** (Python 3.11.15, pytest 7.4.3).
All 18 tests are in `tests/unit/test_invoice_validator.py` and load the validator via an
`importlib` file path — they run without the Flask app, DB, or any fixture invoices.

Root-level `test_basic.py` and `test_pdf.py` are ad-hoc scratch scripts (print-based, no
assertions, not collected by the suite).

**No sample-invoice fixture corpus exists** — the extraction-accuracy harness from LAUNCH.md §0
has nothing to run against. Flagged per CLAUDE.md testing rules.

### 4.2 Coverage map

| Area | Tests? |
|---|---|
| invoice_validator.py | ✅ 18 unit tests (but module unused in pipeline — tests exercise dead code) |
| Parsers (claude/cef/yesss/wholesale/parser_service) | ❌ none |
| Markup application & money maths | ❌ none |
| save_invoice_to_db / upload / queue routes | ❌ none |
| QuickBooks / Xero sync | ❌ none |
| Billing/PayPal (webhook, top-ups, plan transitions) | ❌ none |
| Auth / tenant isolation | ❌ none |
| Customer invoices / quotes / VAT & P&L reports | ❌ none |

### 4.3 Ten highest-value missing tests (in order)

1. **Pipeline integration test: parse → validate → save** — assert `save_invoice_to_db` rejects or
   flags an invoice whose items don't sum to its stated total (forces the validator wiring fix).
2. **Markup maths unit tests** — selling price/profit per line for zero-value lines, credits,
   mixed VAT, discount lines, 2dp Decimal rounding.
3. **PayPal webhook state machine** — forged/unsigned event rejected; ACTIVATED/CANCELLED/
   SUSPENDED/PAYMENT.FAILED transitions set the right user state.
4. **Tenant isolation tests** — user B requests user A's invoice/customer/job-card IDs across
   every resource route; expect 404/403 (catches IDOR regressions like §6.4).
5. **QB sync idempotency** — syncing the same invoice twice creates exactly one bill.
6. **Quota/top-up accounting** — `use_invoice_quota`, bonus invoices, monthly reset, annual
   limits (1,200/yr vs 100/mo boundary).
7. **Parser regression corpus** — golden-file tests on real fixture PDFs per supplier
   (CEF, YESSS, Wholesale, generic Claude path) asserting totals/items.
8. **Token refresh handling** — QB/Xero refresh rotation (mocked), refresh-failure →
   `reconnect_required` / connection deactivation.
9. **Upload validation** — oversized file, wrong magic bytes, corrupt PDF → friendly error,
   no quota burned.
10. **VAT report maths** — VAT return summary totals against a seeded dataset (UK compliance
    is a stated product promise).

---

## 5. Integrations health check

### 5.1 QuickBooks (`app/integrations/quickbooks_service.py`, ~1,700 lines)

**Good:** proactive token refresh with 5-min buffer and refresh-token **rotation** handled
(`:205–215`); 401 → refresh-and-retry with `reconnect_required` flag (`:273–288`); exponential
backoff for 429/5xx honouring `Retry-After` (`:305–356`); user-friendly error parsing (`:411–451`);
vendor dedup by DisplayName (`:508–519`); item dedup by SKU-then-name (`:753–772`); disconnect flow
revokes tokens and soft-deactivates the connection; the app-disconnect webhook verifies the
`intuit-signature` HMAC (`integrations.py:374–424`); static disconnect landing page exists —
**App-Store-review ready** on connect/disconnect.

**Defects:**
- Tokens Fernet-encrypted **only if `TOKEN_ENCRYPTION_KEY` is set**; otherwise silent plaintext
  fallback (`:44–56`). Should fail hard at startup.
- Sync not fully idempotent: `qb_bill_id` written after creation; a crash between QB create and
  DB commit can duplicate bills on retry (`:585–619`). No "already synced" guard at sync start.
- No persistent sync-error history; failures are log-only, so LAUNCH.md §3 "every failed sync
  visible in a status list" has no backing store.
- OAuth `state` falls back to a hardcoded `'random_state'` (`:102`) instead of a per-request nonce.
- ~~The file is **duplicated** at `app/services/quickbooks_service.py` (drifted copy).~~
  ✅ **Deleted** (`fbee76a`) — confirmed unimported; the live copy is `app/integrations/quickbooks_service.py`.

### 5.2 Xero (`app/integrations/xero_service.py`)

- **Tokens stored in plaintext** (`app/models/xero.py:18–19`) — unlike QB. High priority.
- Refresh handled with 5-min buffer and rotation fallback (`:152–174`); refresh failure
  deactivates the connection. Good.
- **Disconnect = hard DELETE with no token revocation** (`integrations.py:961–975`).
- No user-friendly error parsing, no retry/backoff.
- Single-tenant only: `connections[0]` (`integrations.py:925`); fine for now.

### 5.3 Gmail OAuth + IMAP

- Scopes minimal: `gmail.readonly` + `gmail.send` (`gmail_auth.py:20`). Good.
- Tokens Fernet-encrypted, **but** `EMAIL_TOKEN_ENCRYPTION_KEY` is auto-generated into the
  process env if missing (`email_connection.py:61`) — after a restart, every stored Gmail/IMAP
  credential becomes **undecryptable**. Must be a hard startup failure instead.
- Disconnect hard-deletes the row without calling Google's revoke endpoint (`gmail_auth.py:154–168`).
- Refresh failures in `gmail_service.py:31–33` are unhandled — the connection is never marked
  broken, so LAUNCH.md §3 "Gmail connection drops → surfaced" is unmet.
- **IMAP stores the user's mailbox password** (encrypted with the same fragile key)
  (`imap_auth.py:91–97`). Highest-value secret in the DB; prefer provider OAuth where possible
  and a properly managed key. Pre-save connection testing (`imap_fetcher.py:77–111`) is well done.

### 5.4 PayPal (`app/web/billing.py`, `app/services/paypal_service.py`)

- **CRITICAL: `/billing/webhook` performs no signature verification** (`billing.py:322–400`).
  Anyone can POST forged events: `BILLING.SUBSCRIPTION.ACTIVATED` with a crafted
  `custom_id` (`user_<id>_plan_pro_annual`, parsed unauthenticated at `:341–350`) grants a free
  plan; forged CANCELLED/SUSPENDED locks paying users out. Contrast: the QuickBooks disconnect
  webhook *does* verify its HMAC. Use PayPal's verify-webhook-signature API with `PAYPAL_WEBHOOK_ID`.
- Subscription state machine otherwise sensible: ACTIVATED/CANCELLED/SUSPENDED/PAYMENT.FAILED/
  SALE.COMPLETED handled; suspended users lose upload+sync; past_due keeps access with banner;
  `pending_subscription_id` prevents activation races.
- Top-ups validated server-side (quantity bounds, server-computed amount, capture status
  checked) (`billing.py:250–319`). Good.
- **Homepage advertises a £49/£529 "Full Platform" tier that has no PayPal plan, no subscribe
  route, and no in-app equivalent** — see §8.3.

---

## 6. Security pass

### 6.1 Verified strengths

- **Tenant isolation is generally strong** — resource queries filter by `user_id` across
  invoices, customers, job cards, products, etc.
- **No raw SQL with user input** (ORM throughout; `db.text()` only for DDL); **no `|safe`** in
  templates; **no open redirects** (`url_for` everywhere).
- Password policy + bcrypt hashing; password reset uses `secrets.token_urlsafe(32)`, 1-hour
  expiry, single-use (`models/password_reset.py`).
- Upload validation is solid: extension whitelist, MIME + magic-byte checks, 16MB cap, filename
  sanitisation (`utils/upload_validation.py`).
- Security headers, CSP, HSTS, cache-control configured (`app/__init__.py:288–341`).

### 6.2 Findings (ranked)

| Sev | Finding | Location |
|---|---|---|
| CRITICAL | PayPal webhook unauthenticated (see §5.4) — subscription forgery | `billing.py:322–400` |
| HIGH | Default `SECRET_KEY` fallback `'dev-secret-key-change-in-production'`; if env var unset in any deployed env, sessions/CSRF are forgeable | `config.py:9` |
| HIGH | **IDOR**: `JobCard.query.get(job_card_id)` without `user_id` filter when logging labour — labour entries can be linked to another tenant's job card / customer id | `employees.py:114–118` |
| MEDIUM | Cron endpoints **fail open**: if `CRON_SECRET` unset, all `/tasks/*` (trial reminders, expiry handling, email fetch) run unauthenticated | `tasks.py:13–14` |
| MEDIUM | 22 blueprints CSRF-exempt; mitigated by `SameSite=Lax` cookies, but the blanket exemptions are undocumented and easy to regress | `__init__.py:84–100,268–282` |
| MEDIUM | Token-at-rest gaps: Xero plaintext tokens; QB/email encryption silently disabled or auto-keyed when env vars missing (§5) | `xero.py:18`, `quickbooks_service.py:44–56`, `email_connection.py:61` |
| LOW | Hardcoded dev DB password in docker-compose (local-dev only, but normalises bad habit) | `docker-compose.yml:15,30` |
| LOW | OAuth `state` hardcoded fallback `'random_state'` | `integrations quickbooks_service.py:102` |
| LOW | Startup-time inline DDL via `db.create_all()` + raw ALTERs widens runtime DB privileges needed | `__init__.py:35–76` |

---

## 7. Database schema review

### 7.1 Schema documentation (summary)

~29 tables across 22 model modules. Key groups:

- **Supplier invoice core**: `invoice` (totals Numeric; tax columns Float — §2), `invoice_item`
  (well-typed Numeric, indexed `part_number`), `queued_invoice` (email queue with message-id +
  SHA-256 dedup), `supplier_account`, `part_number_correction` (learned OCR fixes).
- **Full platform / CRM**: `customer`, `job`, `job_card`, `customer_invoice(+lines)`,
  `customer_quote(+lines)`, `customer_payment(+allocations)` — money columns all Float (§2),
  created by `add_full_platform_tables.py` and successors.
- **Quote Builder / VTQ (flagged off)**: `project`, `project_material`, `project_labour`,
  `takeoff_item`, `vtq_jobs`, `vtq_transcriptions` — JSON text blobs for parsed data.
- **Integrations**: `quickbooks_connection` (encrypted tokens), `xero_connections` (plaintext
  tokens), `email_connection` (encrypted blob incl. IMAP passwords).
- **Auth/billing**: `user` (subscription fields + **legacy Paddle AND Stripe columns**),
  `password_reset`, `employee` (Jersey social-security defaults), `user_preference`, `product`,
  `product_service`.

Oddities:
- **`invoice.py:53–60`: `bill_status`, `bill_paid_at`, `bill_notes`, `is_receipt` are defined
  twice** (verbatim duplicate block). Python keeps the latter silently; trim it.
- Alembic history needed a merge (`merge_heads_001.py`) and is **bypassed at runtime** by
  `db.create_all()` + inline ALTERs (`__init__.py:35–76`) — drift risk between environments.
- Missing composite indexes for coming workloads: `(invoice_item.invoice_id, part_number)`,
  `(supplier_account.user_id, supplier_name)`.
- No unique constraints on `part_number_correction` or `email_connection` natural keys.
- `qb_bill_id`/`xero_invoice_id` are bare strings (fine, external ids) — but nothing prevents
  double-sync (§5.1).

### 7.2 Price-creep intelligence readiness

**Mostly ready, two gaps.** Already queryable per line item: `part_number` (indexed),
`cost_per_item` (Numeric 10,4), `original_unit_price`, `quantity`, `discount`, via FK to
`invoice` → `supplier_name` (indexed) + `invoice_date`. A per-SKU/per-supplier price history
query is possible today with one JOIN.

Gaps:
1. **Supplier identity is a free-text string** — "CEF", "CEF Ltd", "City Electrical Factors"
   won't group. No supplier master table.
2. **SKU identity is raw OCR output** — `part_number_correction` helps but there's no canonical
   product key linking line items across invoices, and list-price vs negotiated-discount can't
   be distinguished without using `original_unit_price` consistently (regex parsers set it;
   verify the Claude path always does).

**Minimal non-breaking migration path** (additive only):
1. `supplier_master(id, user_id, canonical_name, aliases JSON)` + nullable
   `invoice.supplier_id` FK; backfill by normalising existing `supplier_name` values
   (exact/fuzzy match, user-confirmable).
2. Optional second step when needed: `product_sku(id, user_id, supplier_id, canonical_sku,
   description)` + nullable `invoice_item.sku_id` FK, seeded from `part_number` +
   `part_number_correction`.
3. Price history needs **no new table** initially — it's a view over
   `invoice_item JOIN invoice` once supplier_id exists. Add a materialised
   `sku_price_history` table only if query cost demands it.

Existing rows untouched; old columns remain authoritative until backfill is confirmed.

---

## 8. Dead weight & feature flags

### 8.1 Feature flags

Defined in `app/__init__.py:16–19`, env-driven, default **off**:

| Flag | Gates |
|---|---|
| `ENABLE_VOICE_TO_QUOTE` | `voice_to_quote.py` routes (403 when off) + nav/template sections |
| `ENABLE_QUOTE_BUILDER` | `quotebuilder.py` routes + Ultimate-plan card on billing page |

No other features are flagged. The flag system works, with one template bug — see §8.3.

### 8.2 Dead code inventory

| Item | Evidence | Action |
|---|---|---|
| ~~`app/services/quickbooks_service.py` (1,585 lines)~~ | only `app/integrations/` copy is imported; copies have drifted | ✅ **deleted** (`fbee76a`) |
| `app/parsers/parser_service.py.backup`, `yesss_parser.py.backup` | never imported | delete |
| `app/parsers/upload_fixed.py` | orphaned alternate upload route, not registered | delete |
| `app/services/pdf_service.py` | not imported anywhere (pdf_generator.py is the live one) | delete |
| `test_basic.py`, `test_pdf.py` (repo root) | print-based scratch scripts | delete or move under `tests/manual/` |
| Procfile `worker:`/`beat:` lines | reference `app.celery`, which doesn't exist | remove lines |
| `user.py` Paddle + Stripe columns | PayPal is live; fields unused | keep columns (no destructive migration), mark deprecated |
| `app/tasks/`, `app/api/` packages | empty `__init__.py` only | delete or document intent |
| `migrate_from_pythonanywhere.py` | one-time historical migration | archive |
| Overlapping pairs: `email_sender.py`/`email_service.py`, `symbol_detector.py`/`symbol_detector_ai.py` | both halves still imported | consolidate deliberately, not in this audit |

### 8.3 Pricing inconsistencies (known issue — confirmed, with specifics)

The audit confirms the "homepage pricing inconsistencies" item and pins it down:

1. **Phantom £49 tier**: landing page middle card "Full Platform" shows **£49/mo, £529/yr**
   (`templates/landing/index.html:664–669`). The actual purchasable plan (`full-starter`) is
   **£39/mo, £429/yr** everywhere else: in-app billing page (`billing/index.html:342–347,360–362`),
   manage page, welcome emails (`email_service.py:172–176`), and `billing.py` plan routes. No £49
   PayPal plan env var exists. Either the homepage price is wrong, or a planned price rise never
   reached billing — resolve one way before marketing spend (LAUNCH.md §2 item).
2. **Broken flag scoping renders empty pricing cards**: in the landing pricing section, the
   `{% if config.ENABLE_VOICE_TO_QUOTE %}` blocks are mis-scoped — the first card's entire
   feature list sits inside the flag (`landing/index.html:628–649`), and the second card's `if`
   (`:672`) closes inside the *third* card (`:724`). With the flag off (current default), the
   Sync Starter and Full Platform cards render with **no feature bullets at all**, and the Pro
   card loses its first three. Only the "Voice to Quote" `<li>`s should be flag-wrapped.
3. **Naming drift**: landing "Sync Starter" = in-app "Basic"; landing "Full Platform" =
   in-app "Starter (Full Platform)". Pick one vocabulary.
4. The in-app sync-mode page also shows a flag-gated **Ultimate £99/£1,089** tier
   (`billing/index.html:208–244`) — invisible today, but its PayPal plan env vars
   (`PAYPAL_PLAN_ULTIMATE*`) should exist before the flags ever go on.

---

## Top 10 risks

| # | Risk | File(s) | Impact | Effort to fix | Suggested phase |
|---|------|---------|--------|---------------|-----------------|
| 1 | Invoice validator never called — AI output stored & synced to QB/Xero unvalidated | `web/upload.py:451`, `web/queue.py:292`, `services/invoice_validator.py` | Wrong amounts silently reach customers' books; core product promise unenforced | Small (wire `validate_parse_result()` into `save_invoice_to_db`, set `needs_review`, block sync on errors) | **Now** |
| 2 | PayPal webhook accepts forged events (no signature verification) | `web/billing.py:322–400` | Free subscriptions; paying users locked out; revenue integrity | Small–medium (verify-webhook-signature API + `PAYPAL_WEBHOOK_ID`) | **Now** |
| 3 | Encryption-key handling: email key auto-generated (credentials bricked on restart), QB key silently optional, Xero tokens plaintext | `email_connection.py:61`, `integrations/quickbooks_service.py:44–56`, `models/xero.py:18` | Mass integration outage after a redeploy; token exposure on DB leak | Small (fail-hard startup checks; encrypt Xero like QB) | **Now** |
| 4 | Float money columns + inconsistent rounding regimes. **Phase 1 ✅ (Float→Numeric storage, prod 2026-06-15). Phase 2 ✅ for the supplier-invoice + QB/Xero sync path (`fce9fd6`, 2026-06-18): shared Decimal `money()`, line-authority totals, ROUND_HALF_UP, test corpus. ⏳ STILL OPEN: full-platform customer-document maths still float `round()`** — `customer_invoice.recalculate_totals()`, `customer_quote`, `customer_invoices.py`, `job_cards.py:375–432`, `reports.py`, `tax_reports.py` | Penny drift on **customer invoices & VAT returns** — direct money/compliance errors (supplier-side now correct) | Apply the same `money()` helper to the customer-document/report paths | Pre-launch |
| 5 | Zero tests on critical paths (parsers, markup, sync, billing); no fixture invoice corpus | `tests/` | Regressions invisible; LAUNCH.md accuracy target unmeasurable | Medium–large (start with §4.3 items 1–5) | Pre-launch |
| 6 | IDOR: labour logging reads any tenant's job card; need isolation regression tests | `web/employees.py:114–118` | Cross-tenant data linkage in a financial app | Tiny (filter by `user_id`) + small (test sweep) | **Now** |
| 7 | QB bill sync can duplicate on retry; sync failures not recorded anywhere user-visible | `integrations/quickbooks_service.py:585–619` | Duplicate bills in customers' accounting; silent failures | Small–medium (pre-sync `qb_bill_id` guard + sync-status store) | Pre-launch |
| 8 | Homepage sells a £49 plan that doesn't exist; flag mis-scoping renders empty pricing cards | `templates/landing/index.html:628–724` | Price/billing mismatch at signup; broken-looking pricing page (live today) | Tiny–small | **Now** |
| 9 | Hardcoded model names at 11+ sites; no structured outputs despite CLAUDE.md claim | §3.5 list | Blocks model routing; fragile JSON parsing; painful model migrations | Small (central config) + medium (structured outputs) | Pre-launch / with routing work |
| 10 | Schema managed two ways: Alembic + runtime `db.create_all()`/inline ALTERs; duplicate column defs | `app/__init__.py:35–76`, `models/invoice.py:53–60` | Environment drift; surprise schema changes on deploy | Small–medium (move ALTERs into migrations, drop runtime DDL) | Pre-launch |

*Bubbling under: fail-open cron endpoints (`tasks.py:13`), default `SECRET_KEY` fallback
(`config.py:9`), Gmail/Xero token revocation on disconnect, dead-code cleanup (§8.2).*
