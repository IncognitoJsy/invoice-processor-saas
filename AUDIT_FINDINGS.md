# AUDIT_FINDINGS.md — Imported-line money maths & itemised QuickBooks sync

**Date:** 2026-06-18 · **Branch:** `sprint-a-phase2-markup` · **Scope:** read-only trace, no code changed.

This documents (1) how an imported invoice line's **cost, discount, markup %, selling price
and profit** are calculated, and (2) how the **itemised QuickBooks Products & Services sync**
builds its payload and decides **create vs update**. It then flags **every place a `float` and a
`Decimal` are used together**, which is the open work for AUDIT risk #4 Phase 2 (the parsers/sync
still do binary-float arithmetic; only DB storage is Numeric).

---

## 1. Per-line calculation — the money flow end to end

### 1a. Where it happens

| Stage | File | Lines | Numeric type |
|---|---|---|---|
| Extract → calculate (live path) | `app/parsers/claude_parser.py` `_transform_items()` | 1000–1179 | **float** |
| Admin tiered markup | `app/parsers/claude_parser.py` `_get_admin_tiered_markup()` | 989–998 | float |
| Persist line + invoice totals | `app/web/upload.py` `save_invoice_to_db()` | 451–559 | float → **Decimal** |
| Column types | `app/models/invoice.py` `InvoiceItem` / `Invoice` | 148–171 / 39–93 | **Numeric** |

(Supplier-specific parsers `wholesale_parser.py`, `yesss_parser.py`, `cef_parser.py` have their own
`calculate_markup()` / `calculate_new_prices()` helpers, all float. The Claude parser is the
primary path; the same float→Decimal-at-storage pattern applies to all of them.)

### 1b. The arithmetic (`claude_parser._transform_items`, all in `float`)

1. **Quantity / total** parsed via `float()` (lines 1032, 1038).
2. **Discount** — string stripped of `%`, `float()`-ed → `discount_val` (1046–1049).
3. **Discounted total** (1054–1058): Wholesale supplier → `total_amount * (1 - discount_val/100)`;
   YESSS/CEF/others already discounted → `total_amount` unchanged.
4. **Cost per item** (1060): `round(discounted_total / quantity, 2)` — **per-unit**.
   - Bulk-cable special case (1072–1075): if a 305 m box, `cost_per_item = round(cost/305, 4)` and
     `quantity *= 305`.
5. **Markup** (1082–1088): admin → tiered by discount (`_get_admin_tiered_markup`: 0%→0.20,
   1–30%→0.40, 30–70%→0.50, >70%→0.70); regular user → flat `default_markup/100` (set line 1014).
6. **Effective cost** (1097–1112): if user **not** tax-registered and supplier tax rate > 0,
   `effective_cost = round(cost_per_item * (1 + invoice_tax_rate/100), 2)` (tax-inclusive, since they
   can't reclaim); otherwise `effective_cost = cost_per_item`.
7. **Calculated selling price** (1115): `round(effective_cost * (1 + markup), 2)` — **per-unit**.
8. **QB/Xero price-protection** (1121–1139): if the part exists in `known_products` with a higher
   per-unit `sales_price` (and not >10× calc, i.e. not stale), use it:
   `final_selling_price = round(existing_unit_price * quantity, 2)` and recompute
   `actual_markup = (existing_unit_price - cost_per_item) / cost_per_item`.
9. **Profit** (1141): `round(final_selling_price - effective_cost, 2)`.
10. **Emitted dict** (1152–1168): `cost_per_item=effective_cost`, `total_amount=discounted_total`,
    `selling_price=final_selling_price`, `calculated_selling_price`, `qb_selling_price`,
    `markup_percent=min(int(actual_markup*100), 999)`, `profit_per_item`.

### 1c. Persistence & invoice totals (`upload.py save_invoice_to_db`)

- Validator runs first (469); failures flag `needs_review` + block sync, invoice still saved.
- Invoice totals built in **Decimal** from the float dict values via `Decimal(str(...))`
  (484–492): `total_cost = Σ total_amount`, `total_selling = Σ selling_price × quantity`,
  `total_profit = Σ profit_per_item × quantity`.
- `avg_markup = ((total_selling - total_cost) / total_cost) * 100`, capped (496–499).
- Each `InvoiceItem` field wrapped `Decimal(str(...))` (533–548). Columns are `Numeric` (10,2)/(10,4).

> ⚠️ **`selling_price` / `profit_per_item` change meaning in the QB-override branch.**
> Normally `selling_price` is **per-unit** (`calculated_selling_price` per-unit, step 7), and
> `total_selling = selling_price × quantity` (upload.py 486) is correct.
> But in step 8 (line 1135) `final_selling_price` becomes a **line total** (`unit × quantity`).
> Then upload.py 486 computes `unit × quantity × quantity` → **quantity is squared / double-counted**,
> and `profit_per_item` (1141) subtracts a per-unit `effective_cost` from a line-total selling price.
> The comment at 1124 ("calculated_selling_price is TOTAL") is incorrect — it is per-unit. This is a
> live correctness bug for any line whose part has a higher stored QB/Xero price and quantity > 1.
> *(Calc-semantics issue, independent of the float/Decimal flags below — flagged because it directly
> distorts selling price and profit, which is critical-path per CLAUDE.md.)*

---

## 2. Itemised QuickBooks sync — payload + create-vs-update

**Live module:** `app/integrations/quickbooks_service.py` (confirmed: every importer uses
`from app.integrations.quickbooks_service import QuickBooksService`).
**Trigger:** `app/web/integrations.py` `quickbooks_sync_products()` (626–650) →
`qb.sync_invoice_items_as_products(connection, invoice)`.

### 2a. Build the per-item job (`sync_invoice_items_as_products`, 817–880)

- Loads all `InvoiceItem`s for the invoice (826). Items **without a part number are skipped** (841).
- Builds `item_data` per line (845–853): `name`/`sku` = `part_number`, `description`,
  `cost = float(item.cost_per_item)`, `selling_price = float(item.selling_price)`,
  income/expense account refs from the connection. Calls `create_or_update_item` (855).

### 2b. Create-vs-update decision (`create_or_update_item`, 741–815)

1. **Lookup** via `find_item_by_sku_or_name` (760, defined 720–739): query QB **by SKU first**
   (`find_item_by_sku`, 710–718), then **by Name** (`find_item_by_name`, 699–708). Returns
   `(item, match_type)` where `match_type` ∈ {"sku","name",None}.
2. **Payload** (766–798): `Name`, `Sku`, `Type:"NonInventory"`, `Active`,
   `IncomeAccountRef`/`ExpenseAccountRef`, tax flags (`Taxable`, `SalesTaxIncluded:False`,
   `PurchaseTaxIncluded:False`), optional `SalesTaxCodeRef`, `Description`/`PurchaseDesc`,
   `PurchaseCost = round(float(cost), 2)`, `UnitPrice = round(float(selling_price), 2)`.
   **Prices are tax-exclusive.**
3. **Decision** (800–815): if an existing item was found → **UPDATE**: attach
   `Id` + `SyncToken` + `"sparse": True`, POST to `item`. Else → **CREATE**: POST to `item`
   with no `Id`. (Same endpoint; presence of `Id`/`SyncToken` is what makes QB update vs insert.)

### 2c. Itemised invoice/estimate line detail (`create_invoice`, 1081–1146)

Separate flow that builds `SalesItemLineDetail` lines (not P&S items):
`qty = float(quantity)`, `unit_price = round(float(unit_price), 2)`, `amount = round(qty*unit_price, 2)`,
`GlobalTaxCalculation:"TaxExcluded"`. `add_items_to_invoice` (1148–1280) merges duplicates by
`ItemRef` value, accumulating `Qty` and overwriting `UnitPrice` with the latest.

### 2d. Sync notes (non-float)

- **`results['created']` / `results['updated']` are never incremented** — only `synced` (857–863).
  `create_or_update_item` returns the raw QB response, which doesn't tell the caller which branch ran,
  so the create/update counters in the result dict are always 0. Cosmetic, but the UI/logs can't
  report it.
- **QB query escaping** is manual string interpolation (`find_item_by_*`, 702/712) — fine for now but
  brittle for part numbers containing quotes.
- **Duplicate dead module:** `app/services/quickbooks_service.py` mirrors these functions
  (`create_or_update_item` 774–849, etc.) but is **imported nowhere**. It will silently drift from the
  live `integrations` copy — recommend deleting or clearly marking it.

---

## 3. 🚩 Every place a `float` and a `Decimal` are used together

The pattern is: **all calculation is float; storage is Numeric/Decimal; the QB boundary converts
back to float.** Conversions done via `Decimal(str(x))` are *safe* (string avoids binary-float
artifacts); the flagged risks are the *mixed-type operations* and the *float-into-Numeric* writes.

| # | Location | What co-occurs | Risk |
|---|---|---|---|
| **F1** | `upload.py:499` `avg_markup = min(avg_markup, 999.99)` | `avg_markup` is **Decimal** (built 497), `999.99` is **float** | `min()` mixes types; if the cap fires, a **float** is stored into `Numeric(5,2) average_markup`. Use `Decimal("999.99")`. |
| **F2** | `upload.py:525` `total_ex_tax=float(... or total_cost or 0)` | `total_cost` is **Decimal** (484), wrapped in `float()` | Decimal→float round-trip on a money total before writing to `Numeric total_ex_tax`. |
| **F3** | `upload.py:526` `total_inc_tax=float(... or total_cost or 0)` | same as F2 | same as F2. |
| **F4** | `upload.py:523–524` `supplier_tax_amount/rate=float(...)` | **float** assigned to `Numeric(10,2)/(5,2)` columns | float passed straight into Decimal columns; binary-float value is what gets stored. Should `Decimal(str(...))` like the item fields. |
| **F5** | `upload.py:484–492` `Decimal(str(item[...]))` over parser floats | parser **floats** → **Decimal** | The *safe* boundary, but it imports already-rounded float results — any float rounding error in §1b is frozen into Decimal here. This is the core of risk #4 Phase 2: move the maths upstream into Decimal. |
| **F6** | `quickbooks_service.py:849–850` `float(item.cost_per_item)`, `float(item.selling_price)` | DB **Decimal** → **float** | Money leaves the DB as float for the QB payload. |
| **F7** | `quickbooks_service.py:794,798` `round(float(cost), 2)`, `round(float(selling_price), 2)` | **float** `round()` on values that were Decimal | Final QB `PurchaseCost`/`UnitPrice` computed with binary-float `round()` (banker's rounding), not Decimal. |
| **F8** | `quickbooks_service.py:1110–1112` `float(quantity)`, `round(float(unit_price),2)`, `round(qty*unit_price,2)` | float `round()` on amounts that originate from Decimal columns | Invoice line `Amount`/`UnitPrice` to QB built in float. |
| **F9** | `models/invoice.py:123–125, 182–188` `float(self.total_*)`, `float(self.cost_per_item)` etc. | DB **Decimal** → **float** in every `to_dict()` | All JSON/API reads downcast money to float; any consumer doing further maths is back in float land. |

**Pure-float (no Decimal present, but the root of the imprecision) — risk #4 Phase 2 targets:**
`claude_parser.py` lines 1060, 1074, 1105, 1115, 1127, 1135, 1141 — every `round(..., 2/4)` is a
binary-float `round()`. These should become the shared Decimal `money()` helper with
round-per-line-then-sum, per CLAUDE.md / AUDIT.md risk #4.

---

## 4. Summary of issues surfaced (not fixed)

1. **F1** real type bug: Decimal/float `min()` → float into a Numeric column when the markup cap fires.
2. **F4** floats written directly into `Invoice` Numeric tax columns (inconsistent with item fields).
3. **§1c bug:** `selling_price`/`profit_per_item` semantics flip from per-unit to line-total in the
   QB price-protection branch → `total_selling` squares quantity and profit mixes per-unit cost with a
   line total. Distorts money for any qty>1 line with a higher stored QB/Xero price.
4. **F5–F9 / pure-float list:** all line maths and the QB payload are binary float + `round()`;
   Decimal only appears at the storage boundary. This is exactly AUDIT risk #4 Phase 2.
5. Sync `created`/`updated` counters never incremented (cosmetic).
6. Dead duplicate `app/services/quickbooks_service.py` — divergence risk.

---

# Phase 2b — customer-document / report money (diagnosis, 2026-06-20)

Scope: the customer-facing document path and the tax reports — i.e. the half of AUDIT risk #4
that Phase 2 (`fce9fd6`) deliberately left out. **No code changed in this section — diagnosis
only.** Storage is already Numeric (Phase 1); the defects below are all in the *arithmetic*:
binary-float maths and/or Python `round()` (banker's, round-half-even) instead of Decimal
`money()` (ROUND_HALF_UP). Severity key: 🔴 GST/VAT-return figure · 🟠 customer-facing document
figure (invoice/quote sent for money) · ⚪ render/preview edge (display only).

## 🔴 Highest stakes — VAT/GST-return figures

| # | File:line | Computes | Type | Feeds |
|---|---|---|---|---|
| R1 | `web/tax_reports.py:94` | `net_tax = round(output_tax_total − input_tax_total, 2)` | Python `round()` on Decimal sums (banker's) | **GST return** net tax due |
| R2 | `web/tax_reports.py:103–107` | `round(...)` of input/output tax + net/gross totals | Python `round()` on Decimal sums | **GST return** all boxes |
| R3 | `web/tax_reports.py:78,79,90,91,92` | `sum(inv.tax_amount or 0)`, `sum(inv.subtotal …)` etc. | Decimal sums (cols are Numeric) — but **inherit upstream mis-rounded `customer_invoice.tax_amount`** (see D1/D3) | **GST return** input/output totals |
| R4 | `web/reports.py:171–172` | `output_vat = float(sales.vat)`; `input_vat_estimate = float(net) × float(vat_rate)/100` | **float** arithmetic | **VAT return** box1/box4 |
| R5 | `web/reports.py:177–181` | `box1/4/5/6/7 = round(float, 2)` | `round()` on **float** | **VAT return** HMRC boxes |
| R6 | `web/reports.py:87–117` | `sum(float(r.total/tax_amount/total_cost))`, `round(float, 2/1)` | **float** sums + `round()` | P&L report (revenue, VAT collected, costs, margin) |

Note: `tax_reports` SQL-free totals are Decimal sums (good post-Phase-1), so the report's *own*
rounding is a minor banker's-vs-half-up issue; the real exposure is that it faithfully sums
per-invoice `tax_amount` values that were themselves computed in float/banker's (D1/D3). The
`reports.py` VAT boxes are worse — they do the whole computation in float.

## 🟠 Customer-facing document figures

| # | File:line | Computes | Type | Feeds |
|---|---|---|---|---|
| D1 | `models/customer_invoice.py:63–65` `recalculate_totals()` | `subtotal=Σ line_total`; `tax_amount=round(subtotal×rate/100,2)`; `total=round(subtotal+tax,2)` | Decimal sum but Python `round()` (banker's) | **customer invoice** subtotal/tax/total (the PDF sent for money) |
| D2 | `models/customer_quote.py:40–42` `recalculate_totals()` | same shape as D1 | Decimal sum + `round()` | **customer quote** totals |
| D3 | `web/job_cards.py:425–433` `_recalculate_invoice()` | `subtotal=Σ float(line_total)`; `tax=subtotal×(float(rate)/100)`; `total=subtotal+tax` | **float, tax & total NEVER rounded** → stores e.g. 24.59999 into Numeric(12,2) | **customer invoice built from job cards** |
| D4 | `models/customer_quote.py:82` `calculate_total()` | `line_total=round(qty×unit_price,2)` | `round()` on Decimal (banker's) | quote line total |
| D5 | `web/customer_invoices.py:281` | `existing.unit_price = round((existing.unit_price or 0) + total_selling, 2)` | **`Decimal + float` → TypeError risk** when the line reloads from DB (unit_price is Numeric→Decimal); also banker's `round()` | Materials-Used running total on a customer invoice — **possible live crash**, not just rounding |
| D6 | `web/customer_invoices.py:259,546` | new line `line_total = round(qty × unit_price, 2)` | **float×float** (qty/unit_price taken via `float()` at :236–237, :537–538) | new customer-invoice line totals |
| D7 | `web/customer_invoices.py:249–250,454` | existing line `line_total = round(qty × unit_price, 2)` | `round()` on Decimal cols (banker's); at :454 operands set via `float()` (:447–453) | edited customer-invoice line totals |
| D8 | `web/job_cards.py:375,385,398,409` | line/summary totals: `qty×unit_price` (no round), `Σ float(...)`, `float + float` | **float / unrounded** | job-card→customer-invoice line + Materials summary |
| D9 | `web/customer_invoices.py:777–793` | create-from-JSON: `subtotal/tax_amount/total = data.get(...)`, line `unit_price/line_total` from payload | trusts client floats/strings as-is | manually created customer invoice |

## ⚪ Render / preview edges (display only — not stored; lower priority)

| # | File:line | Note |
|---|---|---|
| V1 | `services/pdf_generator.py:103` `_fmt_money` | `f'£{float(v):.2f}'` — formats a Decimal for the PDF. Lossless for clean 2dp; render edge. |
| V2 | `web/reports.py:223–224`, `web/tax_reports.py:147–172` | CSV `f'{x:.2f}'` export formatting — render edge. |
| V3 | `customer_invoices/new.html`, `customer_quotes/new.html` (line/tax JS) | **client-side preview** (`qty*price`, `subtotal*taxRate/100`) — server `recalculate_totals` is authoritative; ensure server matches. |
| V4 | `invoices/index.html:722`, `quotes/index.html:361` | JS `* 1.05` hardcodes 5% GST in a modal preview — display only, but hardcoded rate is its own (non-Decimal) smell. |

## ⚠️ Cross-check: printed customer tax vs what QB/Xero actually attaches

The customer invoice/quote **tax line is computed locally** from `customer_invoice.tax_rate`
(D1) / the job-card `tax_rate` (D3) as `subtotal × rate/100`. But on sync, the QB/Xero path
(`create_invoice`/`add_items_to_invoice`) attaches a **tax code/TaxType** and lets QBO/Xero
compute the tax (Step 3 resolver: registered → 5% GST code, unregistered → exempt). So the
**printed document and the synced document can disagree** whenever:
- `customer_invoice.tax_rate` ≠ the resolved code's real rate (e.g. doc rate 0 or 20 while the
  resolver attaches GST 5%), or
- the user is **unregistered**: the resolver forces exempt (no output tax), but
  `recalculate_totals` will still add a tax line if `tax_rate > 0`.

So Phase 2b should not only Decimalise these sites but also **drive the customer-document tax
rate from the same source the resolver uses** (registration + the resolved code's rate), so the
PDF the customer receives matches the invoice that lands in their accounting system. This is the
key correctness item beyond rounding — flagged for the fix proposal.

## Summary of what Phase 2b must touch
- 🔴 `tax_reports.py` (R1–R3), `reports.py` VAT boxes + P&L (R4–R6) — GST/VAT-return figures.
- 🟠 `customer_invoice.recalculate_totals`, `customer_quote.recalculate_totals` + `calculate_total`,
  `job_cards._recalculate_invoice`, `customer_invoices.py` line/merge/summary sites (incl. the
  **D5 Decimal+float crash risk**).
- ⚪ render/preview edges: leave as display, but verify they show the Decimal authority.
- ⚠️ reconcile the customer-document tax line with the QB/Xero resolver (registration + rate).

---

# Step 2c — document tax vs resolver (diagnosis, 2026-06-20)

Goal: the tax line on the customer-facing PDF must match the tax that the QB/Xero **resolver**
puts on the synced invoice, so the document a customer receives equals the invoice that lands in
their books. **Diagnosis only — no code changed.**

## (a) Where `customer_invoice.tax_rate` / `customer_quote.tax_rate` is SET

| # | Site | Source of the rate | Gated on `tax_registered`? |
|---|---|---|---|
| S0 | `models/customer_invoice.py:25`, `customer_quote.py:19` | column **default `0`** | n/a |
| S1 | `web/customer_invoices.py:203` (auto-create from a supplier invoice) | `current_user.tax_rate or 0.0` | **No** |
| S2 | `web/customer_invoices.py:781` (`create_manual`) | client `data.get('tax_rate')` (the form posts `current_user.tax_rate` — `new.html:193,354`) | **No** |
| S3 | `web/job_cards.py:294` (job-card → customer invoice) | **hardcoded `tax_rate=0`** | **No** (ignores config entirely) |
| S4 | `web/customer_quotes.py:83` (quote create) | `current_user.tax_rate or 0.0` | **No** |
| S5 | `web/customer_quotes.py:282,346` (quote → invoice convert) | copies the **stored `quote.tax_rate`** snapshot | **No** (snapshot can be stale vs current registration) |
| S6 | `web/customer_quotes.py:417` (`create_manual` quote) | client `data.get('tax_rate')` | **No** |

Net: the document rate is **whatever `current_user.tax_rate` happened to be at create time**
(S1/S2/S4), a **stale snapshot** (S5), **client-supplied** (S2/S6), or **hardcoded 0** (S3) —
and **none of them check `tax_registered`**. `tax_rate` is an independently-settable/stale value.

## (b) Document tax line vs resolver — exact divergence cases

- **Document tax line:** `recalculate_totals()` → `tax_amount = money(subtotal × tax_rate / 100)`.
  So `tax_rate > 0` ⇒ a tax line at that rate; `tax_rate == 0` ⇒ no tax line. Driven solely by
  the stored `tax_rate` (per the set-sites above).
- **Resolver on sync** (`resolve_output_tax`): **unregistered → exempt** (no output tax);
  **registered → the matched/sole QBO `TaxCode`'s real rate** (single-code fallback uses the sole
  code's `TaxRateRef` rate regardless of `user.tax_rate`; multi-code disambiguates by
  `user.tax_rate`); **registered + nothing resolvable → fail closed** (`TAX_CODE_UNRESOLVED`,
  blocks sync).

Divergences (PDF ≠ synced books):

| Case | Document shows | Resolver attaches | When it happens |
|---|---|---|---|
| **D-A** unregistered, `tax_rate > 0` | tax at `tax_rate`% | **exempt** (no tax) | any unregistered user with a non-zero `tax_rate` (stale config; S1/S2/S4 copy it ungated). Live account is `tax_rate=0` so safe **by luck**. |
| **D-B** registered, job-card invoice | **£0 tax** (S3 hardcodes 0) | GST at the code's rate | every job-card→invoice for a registered user — PDF has no tax, books do |
| **D-C** registered, rate mismatch | `current_user.tax_rate`% (e.g. 20, or 0 if unset) | the **sole code's real rate** (e.g. 5%) | registered user whose `tax_rate` ≠ the QBO code's rate, incl. the **registered-but-`tax_rate`-unset** case (doc shows no tax; sync attaches the code rate) |
| **D-D** quote→invoice convert | the quote's **snapshot** rate (S5) | current registration/rate | registration or rate changed between quote creation and conversion |
| **D-E** manual create | **client-supplied** rate (S2/S6) | config/registration | a crafted or stale client value on `create_manual` |

## Display twins (client-side previews that also encode a rate)

- `customer_invoices/new.html:193` & `customer_quotes/new.html:175`: `const taxRate = {{ current_user.tax_rate or 0 }}` → JS preview `subtotal × taxRate/100`. Config-derived but **not gated on `tax_registered`** (an unregistered user with a stale rate previews tax). The form then POSTs this rate into `create_manual` (S2/S6).
- **V4 (from Phase 2b):** `invoices/index.html:722`, `quotes/index.html:361` — `* 1.05` **hardcodes 5% GST** for the "total with GST" modal preview, regardless of registration or actual rate (wrong for VAT/20% or unregistered users).

## Out of scope (note — do NOT build in 2c)
- **Per-line mixed VAT rates** (UK 0/5/20 on one invoice) — a separate future feature; 2c assumes a single document rate.
- **Live-querying the resolver at document-generation time** — we rely on the shared user config as the single source; the resolver's existing **fail-closed** behaviour protects against a genuine QBO code mismatch (it blocks the sync rather than producing divergent books).

## Adjacent gap noticed (not 2c, flag only)
`customer_quotes.py:417` `create_manual` (quote) still trusts client `subtotal`/`tax_amount`/`total`
— the same shape as invoice D9, which Phase 2b fixed for invoices but **not** for quotes. Worth a
follow-up (recompute server-side). *(Fixed as part of 2c — quote manual create now recomputes
line totals + `recalculate_totals` server-side.)*

## Step 2c — RESOLVED (implementation, 2026-06-20)

Single source of truth: `app/utils/tax.py` `effective_output_rate(user) = tax_registered ? tax_rate : 0`.
- **Document side (Decision 1 — snapshot at create, immutable):** S1–S6 now snapshot
  `effective_output_rate(current_user)` — killed the hardcoded `0` (S3 job-card), the
  client-trust values (S2/S6), and the stale quote snapshot (S5, which now snapshots CURRENT
  config at conversion). `recalculate_totals` keeps using the STORED rate, so a later settings
  change never rewrites an issued document.
- **Resolver side (Decision 2 — match-or-fail):** QB & Xero resolvers target
  `effective_output_rate(self.user)`; the matched code/TaxType's REAL rate must equal it within
  tolerance, else **fail closed** (the 3c single-code-regardless and the keyword/country fallbacks
  are removed). Unregistered → exempt.
- **Guard:** registered-but-rate-unset blocks document create (every create route) and settings
  save; sync is blocked by the resolver's fail-closed.
- **Display twins:** `new.html` JS `taxRate` gated on registration; the list-modal `* 1.05`
  preview is now config-derived (`1` when unregistered).

### Residual edge (accepted, documented)
A full-platform user who BOTH sends a `CustomerInvoice` PDF **and** separately syncs the
underlying supplier `Invoice` to QB/Xero for the same job, **and changes their configured rate in
between**, can end up with the PDF (snapshot, old rate) and the QB/Xero invoice (resolver, new
rate) differing. This is inherent to the two being separate artifacts from different objects (the
PDF never syncs; the supplier invoice carries no output-rate snapshot). It's rare, and the
resolver's **fail-closed** still prevents a genuine code mismatch from silently producing wrong
books — it blocks the sync instead. Threading a single per-object snapshot through both would be
Option B (over-coupling), explicitly not taken.

---

# Tracked follow-up — transient TaxRate-read failure → false fail-closed (reliability)

> **✅ SUPERSEDED (2026-06-23) by the output tax-code PICKER** (commits `126898e`→`fab37b0`; see
> "Output tax-code picker" below). The per-sync **`TaxRate` rate read + match-or-fail** this
> follow-up was going to harden **no longer exists** — registered syncs attach the user's
> *picked* code by stored ref, so there is no per-line rate read to rate-limit. The only
> remaining provider read on the registered path is a **transient-safe existence check** (is the
> picked ref still in the live code list? empty/unavailable list → `unresolved`, never a false
> "stale"), which cannot produce the false fail-closed described here. No retry+cache built.

**Tag:** pre-go-live reliability — **NOT money-correctness** (no wrong amounts, no writes at risk).
**Surfaced by:** `scripts/dryrun_customer_invoice_sync.py` against production (2026-06-22). The same
registered-5% dry run resolved `taxable (GST id 2)` on one execution but **fail-closed
(`TAX_CODE_UNRESOLVED`, sync blocked)** on a back-to-back execution, with identical config/data.

**Root cause:** the QB resolver's match-or-fail reads each code's real rate from its
`TaxRateRef → TaxRate.RateValue`. `_fetch_active_tax_rates` issues `SELECT * FROM TaxRate` and
**swallows any error → returns `{}`**; `_code_sales_rate` then falls back to parsing the rate from
the code's *name* ("GST" has no `%`) → `None` → no rate matches the configured rate →
fail-closed. The rate read is **re-fetched per line** (single dry run did ~30 QBO GETs across
3 scenarios × 7 items + tax-code/rate queries), which tripped QBO **rate-limiting**; a 429/transient
failure then empties `rate_map` and blocks an otherwise-valid registered sync.

**Fix direction (when addressed):** make the TaxRate read resilient —
1. **retry-with-backoff** on the `TaxRate` query (the service already has backoff for the data
   API; apply it here), and
2. **cache the TaxRate read once per sync** (fetch `rate_map` a single time, not per line/per
   `resolve_output_tax` call).

**Explicitly NOT the fix:** do **not** "trust the sole code's rate on read error" / re-introduce a
single-code-regardless leniency — that re-opens the silent-rate assumption Step 2c deliberately
removed (the document could show one rate while QBO applies another). Fail-closed on a genuine
unknown is correct; the goal is only to stop *transient read failures* from masquerading as
"unknown rate". The Xero resolver (`_tax_rate_value`) has the same shape — apply the same
retry + per-sync cache there.

---

# Output tax-code PICKER (2026-06-23) — durable replacement for the match-or-fail rate read

Commits `126898e` (storage) · `43a8a38` (read-only picker endpoint) · `d415eee` (Settings UI +
save) · `6349c01` (QB resolver) · `247447b` (Xero resolver) · `fab37b0` (stale-ref + disconnect).
Branch `sprint-a-phase2-markup`. Full suite **174 green**.

**What it does.** A registered user picks their output sales tax code **once**, from a read-only
dropdown populated from their connected accounting software (`GET /settings/tax-codes`). The pick
is stored on `User` (`output_tax_code_ref` / `output_tax_code_name` / `output_tax_provider`, with
`tax_rate` = that code's rate captured at pick time, re-validated server-side at save). At sync the
resolver attaches the **picked ref directly** — no per-sync `TaxRate` read, no rate-match. This
supersedes the Step 2c/3c match-or-fail entirely (`_select_taxable_code` / `_select_taxable_tax_type`
deleted; the rate-discovery helpers remain, now used only by the picker's `list_sales_tax_codes`).

### 🚨 RELEASE NOTE — registered + connected users MUST re-pick once after deploy

Existing **GST/VAT-registered users with QuickBooks or Xero connected — including our own
Proton.je account — must visit Settings → "Output tax code" and pick their code once after this
ships, or their syncs will fail closed.** This is a **safe** regression: the sync **blocks**
(`TAX_CODE_UNRESOLVED`), it never mis-rates or silently syncs tax-free. The Settings page surfaces
it with an **amber "Pick your output tax code" prompt**. For Proton.je this is **absorbed into the
go-live config step** (pick GST id 2 once). Unregistered users are unaffected (still pushed exempt).

**✅ DONE (2026-06-23) — picked code surfaced on the PDF.** `pdf_generator._totals_block` now
labels the tax line with the picked code name + the document's snapshot rate, with the tax amount
in the adjacent column — e.g. `GST (5%)` | `£5.00` (helpers `_tax_label` / `_fmt_rate`; the latter
trims trailing zeros so `5.00` → `5`). Applies to all 6 invoice templates (all share
`_totals_block`); falls back to the generic `tax_type`, then `'Tax'`, when no pick is stored. The
code *name* is read from the user's current pick (not snapshotted on the document) — same A2 class
of edge as the stored rate. Tests: `tests/unit/test_pdf_tax_label.py`.

> **✅ FIXED (2026-06-23, own commit) — customer-quote PDF was a live 500.** `customer_quotes.py`
> imported `generate_quote_pdf` from `pdf_generator.py`, which **never defined it** (only
> `generate_invoice_pdf`) — broken since the feature shipped (`7b6ad29`), not a refactor drop. Both
> user-reachable routes failed: GET `/customer-quotes/<id>/pdf` (Download PDF button) raw-500'd, and
> POST `/customer-quotes/<id>/send` returned the raw ImportError to the UI. Fix adds
> `generate_quote_pdf(quote, user)` reusing the invoice templates + `_totals_block` (so it inherits
> this tax label) via a thin `_QuoteDoc` adapter (`quote_number`/`expiry_date`/no payment-terms);
> builders aren't forked. Tests: `tests/unit/test_quote_pdf.py`, `tests/integration/test_quote_pdf_routes.py`.
> **✅ FOLLOW-UP DONE (2026-06-23, own commit) — quote wording.** A doc-type label dict
> (`_INVOICE_LABELS` / `_QUOTE_LABELS`) is threaded `_render → builders → _totals_block`, so quote
> PDFs read **'QUOTE' / 'TOTAL' / 'Valid Until'** (matching `expiry_date`) instead of
> 'INVOICE' / 'TOTAL DUE' / 'Due Date'. Builders take a `labels=` param (default = invoice labels),
> so nothing was forked and invoices are unchanged. Asserted on the real rendered PDF text
> (pdfminer) in `tests/unit/test_quote_pdf.py`.

### Sync block states
- **`TAX_CODE_UNRESOLVED`** — registered user with **no pick** (or a transient/empty code list).
  → "pick it in Settings".
- **`TAX_CODE_INVALID`** *(new, commit `fab37b0`)* — registered user whose **picked code is no
  longer in the provider** (deleted/archived since picking; confirmed by a non-empty live list that
  lacks the ref). → "re-pick it in Settings". A transient/empty list is treated as `UNRESOLVED`,
  never `INVALID`, so a read blip can't masquerade as a stale pick. The Settings picker also flags a
  stale pick proactively (`current.valid = false` → amber re-pick prompt) before any sync.
- **Disconnect clears the pick** (`clear_picked_output_code`, provider-scoped) on QB/Xero
  disconnect + the Intuit-side disconnect webhook, so a stale ref can't survive a reconnect/switch.

### A2 — stored-rate staleness (accepted edge, documented; sibling of the 2c residual edge)
The picked **rate is a snapshot** taken at pick time (and the resolver attaches the code by ref,
not by rate). If the provider later **changes the rate behind the same code id** (e.g. a "GST" code
goes 5% → 7% in QBO while keeping its id), the printed document (snapshot rate) and the synced
invoice (provider re-computes from the code) **diverge until the user re-picks** — re-picking
re-reads and re-snapshots the current rate. Rare and low-stakes (rate changes behind a stable id
are unusual), and the code id is still correct so the books aren't *wrong*, just differently-rated
between the two artifacts. **Periodic re-validation** (background re-read of the picked code's rate,
flagging drift) is noted as a **later option — not built.** This sits next to the Step 2c residual
edge (PDF vs separately-synced supplier invoice when the rate changes between).
