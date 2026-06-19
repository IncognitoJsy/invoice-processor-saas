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
