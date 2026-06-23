# Risk #4 — Phase 2 Plan: Decimal money maths

**Status:** planned, not started. Phase 1 (Float→Numeric storage migration,
`money_float_to_numeric`) is DONE and verified in production (2026-06-15).
Phase 2 converts the live arithmetic from binary float + `round()` to Decimal.
**Risk #4 is not closed until Phase 2 lands.**

To be executed next session against a fixed staging environment.

---

## Scoping lens

The site sweep found ~30 `round()` sites; not all are money or in scope.

- **Money, in named scope (Tiers 1–3):** recalc methods, customer-invoice /
  job-card lines, VAT/P&L reports, QB/Xero sync + the Xero price comparison,
  parser markup/discount.
- **Money, but flagged-off or peripheral (Tier 4):** `voice_to_quote.py` and
  `quotebuilder.py` (feature-flagged off), `project.py`, `supplier_quotes.py`,
  `employee.to_dict`, `product_service` margin props.
- **Not money — exclude:** `takeoff.py` geometry (`area_sqm`, `length_metres`),
  `quotebuilder` `px_per_metre`/`real_width_m`. Measurements; leave as float.

---

## (1) Every float money site still doing `round()` / float math

### Tier 1 — customer-facing documents + compliance (highest risk)
- `models/customer_invoice.py:64–65` — `recalculate_totals` tax/total,
  `round(...,2)` on Decimals now → banker's rounding.
- `models/customer_quote.py:40–42, 82` — quote subtotal/tax/total + line total.
- `web/customer_invoices.py:249–250, 259, 281, 454, 546` — line totals / unit
  price, `round(...,2)`.
- `web/job_cards.py:375, 385, 398, 409, 430, 432–433` — **the unrounded ones**:
  merged/new line totals and `_recalculate_invoice` tax/total stored with **no
  rounding at all** (the audit's worst offender).
- `web/tax_reports.py:78–107` — VAT return: sums Float-derived values, rounds
  only at output.
- `web/reports.py:87–117, 171–181` — P&L + VAT estimate, float aggregation,
  output rounding.

### Tier 2 — sync to accounting systems
- `integrations/quickbooks_service.py:794, 798, 1111–1112, 1213, 1237, 1348,
  1469, 1537–1538` — UnitPrice / Amount `round(float(...),2)`.
- `integrations/xero_service.py:482` — **raw float `>` price comparison**
  (`sale_price > existing_sale_price`), plus `UnitAmount` passthrough at 522/572.

### Tier 3 — extraction (markup / discount)
- `parsers/yesss_parser.py:156, 159, 214–215, 220, 231` and
  `wholesale_parser.py:172–292` — `cost × (1+markup)`, discounts,
  `original_unit_price = cost/(1−disc)`.
- `web/upload.py:593` — catalogue sync sale price.
  (`upload.py:484–499` already uses Decimal correctly — reference pattern.)

### Tier 4 — found, out of named scope (decide: include or defer)
`project.py:83, 222, 228–229, 281`; `voice_to_quote.py` (flagged off);
`quotebuilder.py` money lines; `supplier_quotes.py:148, 396–400`;
`employee.py:61–63, 117–119`; `product_service.py:30, 36`.

---

## (2) The `money()` helper — reuse or extract?

**Recommendation: new pure-stdlib `app/services/money.py` for all live code; the
validator keeps its private `_money`/`_to_decimal`.**

Why the validator can't import the shared one: its unit test loads
`invoice_validator.py` by file path (`exec_module`) *specifically to avoid
importing `app`*. Any `from app.services.money import …` would trigger
`app/__init__.py` (Flask + the risk #3 key validator) and defeat that isolation.

`app/services/money.py` — imports only `decimal`. API:
- `to_decimal(v)` → `Decimal | None`, always via `Decimal(str(v))` (never
  `Decimal(float)` — see Q5), handling `£`/`,`/`%`/`None`/`'None'`.
- `money(v)` → 2dp `ROUND_HALF_UP` (amounts/totals/tax).
- `price(v)` → 4dp, `qty(v)` → 3dp, `rate(v)` → 2dp (match Phase 1 column scales).
- `line_total(quantity, unit_price)` → `money(qty(quantity) * price(unit_price))`
  — round-per-line.

`ROUND_HALF_UP` everywhere — matches the validator *and* the Postgres `::numeric`
cast Phase 1 used (round-half-away-from-zero), so code rounding now agrees with
how the stored data was migrated. (Today's `round()` is banker's — see Q5.)

The validator keeps its 2 private functions; add a `test_money_helpers_agree`
asserting the shared `money()` and validator `_money()` produce identical output
across a sample, so they can't silently diverge.

---

## (3) Test corpus to prove correctness

New `tests/unit/test_money.py` (helper) + `tests/integration/test_money_pipeline.py`
(recalc/reports), building the money fixture corpus the audit says is missing.

- **Helper:** half-up at `.005` boundaries; negatives (credits/refunds);
  float-noise inputs (`0.1+0.2`); `None`/empty/`'£1,234.56'`; 2/3/4dp variants.
- **Recalc (customer invoice/quote):** single line 20% VAT; multi-line where
  per-line-then-sum ≠ sum-then-round (proves the chosen convention); 0% (Jersey),
  5%, 20% VAT; discount lines; credit (negative line → negative total);
  fractional `quantity(3dp) × unit_price(4dp) → line_total(2dp)`.
- **VAT return / P&L:** sum of per-invoice tax equals report box totals; assert
  `subtotal + tax == total` exactly (no penny drift) and line-sum == subtotal.
- **Markup (parsers):** `cost×(1+markup)` at boundaries; 0%, large, 999.99 cap;
  discount `cost/(1−disc)`.
- **Sync:** QB/Xero amount builders produce `qty×unit_price` equal to the stored
  `line_total`; the Xero comparison fires correctly on quantized Decimals.
- **Property/golden:** a handful of representative invoices, recompute, assert
  internal consistency.

---

## (4) Conversion order, each with its verification

Phased with checkpoints, smallest-blast-radius and most-testable first:

0. **`money.py` + its unit tests.** Verify in isolation. No behaviour change.
1. **Model recalc methods** (customer_invoice, customer_quote). Pure,
   unit-tested → exact Decimal assertions. Run full suite.
2. **Web line calcs** (customer_invoices.py, then the unrounded job_cards.py —
   highest drift). Integration tests via `app.test_client()`.
3. **Reports / VAT** (tax_reports.py, reports.py). Tests with known invoices;
   assert box totals.
4. **Sync** (QB then Xero, incl. the `>` comparison → compare quantized
   Decimals). Unit-test the payload/amount builders; manual QB/Xero sandbox sync
   on staging.
5. **Parsers** (yesss/wholesale) + upload catalogue sync. Tests with sample line
   dicts.
6. **(If in scope) Tier 4**, last.

Cross-cutting verification: a lint-style test asserting `round(` / bare `float(`
don't reappear in the converted money modules; full `pytest` after each step;
staging deploy + sandbox sync before anything customer-facing reaches prod.

---

## (5) What could silently (or loudly) go wrong

1. **`Decimal × float` → TypeError.** Any converted value meeting a float literal
   (e.g. `subtotal * 1.2`) raises. **Some is already latent from Phase 1** — only
   masked because customer tables are empty in prod. Every operand in a converted
   path must be Decimal. Loud, but hides in untested/flagged-off paths.
2. **`Decimal(float)` precision corruption.** `Decimal(0.1)` = `0.1000…0055`.
   Always go through `to_decimal()`/`str()`. Silent. Helper enforces it; tests use
   noisy inputs.
3. **`jsonify(Decimal)` raises — no Decimal JSON encoder exists.** After
   conversion, `to_dict()` returns Decimal → API endpoints 500. Needs a global
   Flask JSON provider for Decimal (recommended) or cast at each boundary.
   Cross-cutting decision; covered by API tests.
4. **Template math.** Jinja `{{ qty * unit_price }}` / formatting now sees Decimal
   — renders fine as text, but arithmetic with float constants can raise / format
   differently. Render templates in tests + manual UI check.
5. **Rounding-mode change (banker's → half-up).** Values at exact `.5` boundaries
   change (`round(2.5)=2` → `3`). Intentional (aligns code with Phase 1 storage),
   but a behaviour change — first recalc of an affected invoice may shift a penny.
   Document it.
6. **Per-line-then-sum vs sum-then-round.** Changing where rounding happens
   changes totals by pennies. Pick **round-per-line-then-sum** (audit's
   recommendation) and apply everywhere; some totals will differ from pre-Phase-2
   by design.
7. **Comparisons / keys.** Decimal vs float comparison raises; the Xero `>` must
   quantize both sides. `Decimal('1.0') == Decimal('1.00')` is True but be wary
   using money as dict/set keys.
8. **SQL `SUM` returns Decimal** in some reports vs Python `sum` of floats
   elsewhere — mixing. Audit the report queries during Tier 3.

---

## Decisions needed before writing code

1. **Scope:** Tiers 1–3 only (named scope), or include Tier 4 (project module +
   flagged-off VTQ/quotebuilder)? Recommended: 1–3 now, Tier 4 follow-up,
   geometry excluded.
2. **Rounding convention:** confirm `ROUND_HALF_UP` + round-per-line-then-sum as
   the house rule (aligns code with the Phase 1 migration).
3. **JSON serialization:** OK to add a global Decimal JSON provider (cleanest), vs
   casting at each `to_dict`?
4. **Sub-PRs:** land as the phased sequence above (helper → recalc → web → reports
   → sync → parsers), each its own reviewed commit through staging — rather than
   one big change?

---

## Pre-flight for next session

- Staging must be fixed first (it was empty/drifted — risk #10 — and the Phase 1
  deploy crashed there on a missing `invoice` table). Seed staging from a prod
  dump so it's a faithful mirror before executing Phase 2 against it.
- Local `.env` already holds throwaway encryption keys (gitignored) so `flask`
  commands run locally.
- Branch for this work: `plan/risk4-phase2-decimal-math` (holds this plan).
