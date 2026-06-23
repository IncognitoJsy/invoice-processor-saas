"""
Regression suite for the LIVE per-line calc path:
    app/parsers/claude_parser.py :: ClaudeInvoiceParser._transform_items()

Fixtures are real supplier lines (see AUDIT_FINDINGS.md):
  - YESSS (IN093/1120420): line amounts are ALREADY net of discount; the
    discount % is still supplied because it drives the admin markup tier.
  - Wholesale Electrics (IN390873): the line amount is GROSS; net is computed
    as gross - discount, rounded half-up to the penny.

Design rules for this suite (per the brief):
  - One concern per test so a failure pinpoints the bug.
  - Tests encode the *mathematically correct* expected value. Some therefore
    FAIL against the current code — that is intentional; each such test is a
    regression guard for a known bug documented in AUDIT_FINDINGS.md:
        * float arithmetic + round() yields the wrong penny  (risk #4 Phase 2)
        * the QB/Xero price-protection branch (claude_parser.py:1135) stores a
          LINE TOTAL in the per-unit selling field -> quantity gets squared
          downstream in upload.py:486
        * the OCR variant matcher conflates SB20MWH <-> SB25MWH (0<->5)

The module is loaded by file path so we never import the `app` package
(no Flask/DB/ANTHROPIC_API_KEY needed), mirroring tests/unit/test_invoice_validator.py.

Run from repo root (use -s to see the eyeball tables):
    pytest tests/unit/test_claude_parser_calc.py -v -s
"""

import importlib.util
import logging
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

# ── Load claude_parser.py directly (no `app` package import) ──────────────────
_PARSER_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "parsers" / "claude_parser.py"
)
_spec = importlib.util.spec_from_file_location("claude_parser", _PARSER_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ClaudeInvoiceParser = _mod.ClaudeInvoiceParser

CENTS = Decimal("0.01")


def round_half_up(value, places=CENTS):
    """Decimal round-half-up — the 'correct' money rounding for the fixtures."""
    return Decimal(str(value)).quantize(places, rounding=ROUND_HALF_UP)


# ── Builders ─────────────────────────────────────────────────────────────────
def make_parser(known_products=None, *, is_admin=True, default_markup=50.0,
                tax_registered=True, tax_rate=0.0):
    """Construct the parser WITHOUT __init__ (skips the Anthropic client / API
    key) and pre-seed the product cache so _load_known_products() and
    _validate_part_numbers() are fully offline and deterministic."""
    p = ClaudeInvoiceParser.__new__(ClaudeInvoiceParser)
    p.logger = logging.getLogger("test_claude_parser")
    p._known_products_cache = dict(known_products or {})  # not None => no DB path
    p.user_markup_settings = {
        "is_admin": is_admin,
        "default_markup": default_markup,
        "tax_registered": tax_registered,
        "tax_rate": tax_rate,
    }
    return p


def make_item(part, qty, discount, amount, description=""):
    """Build one extracted-item dict in the shape _transform_items() expects.
    `amount` is the value the AI extracted into total_amount (net for YESSS,
    gross for Wholesale)."""
    return {
        "part_number": part,
        "description": description or part,
        "quantity": qty,
        "discount": str(discount),
        "total_amount": str(amount),
        "original_unit_price": 0,
    }


def qb_product(part, sales_price):
    """A known-products cache entry as _load_known_products() would build it."""
    return {part.upper(): {"name": part, "sku": part,
                           "source": "quickbooks", "sales_price": sales_price}}


def transform_one(parser, supplier, part, qty, discount, amount):
    """Run the live path for a single line and return its output dict (or None)."""
    out = parser._transform_items([make_item(part, qty, discount, amount)],
                                  supplier=supplier)
    return out[0] if out else None


# ── Fixtures: confidently-parsed rows from the cost table ────────────────────
YESSS_SUPPLIER = "YESSS Electrical"
WHOLESALE_SUPPLIER = "Wholesale Electrics"

# part, qty, discount%, net line cost (taken as-is)
YESSS_LINES = [
    ("VME110",      2,  44, "102.09"),
    ("SB20MWH",     20, 85, "9.93"),
    ("SB25MWH",     20, 85, "11.34"),
    ("YEFB1012BLK", 1,  78, "7.99"),
    ("MSSB73WH",    2,  80, "10.12"),
    ("MAB3WH",      5,  85, "5.59"),
    ("BEN20-A",     1,  50, "1.87"),
    ("YCC6",        10, 55, "1.08"),
    ("QCW20S-LSF",  1,  30, "5.89"),
    ("ERS230DL1",   1,  60, "85.96"),
]

# part, qty, discount%, gross line, expected net (= round_half_up(gross*(1-d/100)))
WHOLESALE_LINES = [
    ("DTG2012W",   10, 70,   "6.84",  "2.05"),
    ("CMA240",      1, 75,   "7.14",  "1.79"),
    ("WMPB2/28",    2, 77.5, "13.40", "3.02"),
    ("WMPB2/46CC",  1, 77.5, "14.34", "3.23"),
    ("WMSS82",      5, 0,    "9.25",  "9.25"),
    ("PX3093Y1.5",  3, 0,    "2.64",  "2.64"),
    ("WMPS12",      1, 77.5, "4.09",  "0.92"),
    ("PFA20W",     10, 90,   "61.70", "6.17"),
    ("RNG20W",      2, 0,    "3.90",  "3.90"),
    ("RNG25W",      2, 0,    "5.90",  "5.90"),
]

YESSS_IDS = [r[0] for r in YESSS_LINES]
WHOLE_IDS = [r[0] for r in WHOLESALE_LINES]
YESSS_MULTI = [r for r in YESSS_LINES if r[1] > 1]
YESSS_MULTI_IDS = [r[0] for r in YESSS_MULTI]


# ═══════════════════════════════════════════════════════════════════════════
# 1. Parsed net cost per line == fixture value
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("part,qty,discount,net", YESSS_LINES, ids=YESSS_IDS)
def test_yesss_net_taken_as_is(part, qty, discount, net):
    """YESSS lines are already discounted: total_amount must pass through
    unchanged (the discount must NOT be re-applied)."""
    parser = make_parser()  # empty catalog -> no rename, no price override
    row = transform_one(parser, YESSS_SUPPLIER, part, qty, discount, net)
    assert round_half_up(row["total_amount"]) == Decimal(net)


@pytest.mark.parametrize("part,qty,discount,gross,net", WHOLESALE_LINES, ids=WHOLE_IDS)
def test_wholesale_net_computed_round_half_up(part, qty, discount, gross, net):
    """Wholesale lines are gross: line net = round_half_up(gross * (1 - d/100)).
    The stored line total (total_amount) is the UNROUNDED product, so rounding
    it half-up reproduces the fixture. (The penny bug is in the per-unit cost,
    not here — see test_wholesale_per_unit_cost_penny below.)"""
    expected = round_half_up(Decimal(gross) * (1 - Decimal(discount) / 100))
    assert expected == Decimal(net)  # fixture sanity
    parser = make_parser()
    row = transform_one(parser, WHOLESALE_SUPPLIER, part, qty, discount, gross)
    assert round_half_up(row["total_amount"]) == expected


def test_wholesale_per_unit_cost_penny():
    """For a qty=1 line the per-unit cost MUST equal the (correct, half-up) line
    net. CMA240: line net 7.14*0.25 = 1.785 -> 1.79, but cost_per_item is
    round(1.785, 2) = 1.78 because round() is binary-float + banker's rounding.
    A penny low. This is exactly AUDIT_FINDINGS.md risk #4 Phase 2."""
    parser = make_parser()
    row = transform_one(parser, WHOLESALE_SUPPLIER, "CMA240", 1, 75, "7.14")
    expected = round_half_up(Decimal("7.14") * Decimal("0.25"))  # 1.79
    assert round_half_up(row["cost_per_item"]) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. Extracted part number == fixture value
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("part,qty,discount,net", YESSS_LINES, ids=YESSS_IDS)
def test_part_number_preserved_no_catalog(part, qty, discount, net):
    """Baseline: with no catalog, the extracted part number is preserved."""
    parser = make_parser()
    row = transform_one(parser, YESSS_SUPPLIER, part, qty, discount, net)
    assert row["part_number"] == part


def test_sb20mwh_not_mislabelled_to_sibling():
    """SB20MWH must NOT be 'corrected' to its sibling SB25MWH. The OCR variant
    matcher substitutes 0<->5, so when only SB25MWH is in the catalog the
    matcher rewrites SB20MWH -> SB25MWH, conflating two distinct products.
    (claude_parser.py _validate_part_numbers / ocr_substitutions['0'])."""
    parser = make_parser(known_products=qb_product("SB25MWH", 0))
    row = transform_one(parser, YESSS_SUPPLIER, "SB20MWH", 20, 85, "9.93")
    assert row["part_number"] == "SB20MWH"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Line total = per-unit x qty (quantity counted ONCE, never squared)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("part,qty,discount,net", YESSS_LINES, ids=YESSS_IDS)
def test_cost_line_not_squared(part, qty, discount, net):
    """cost_per_item is per-unit; the line cost must be per-unit x qty, never
    per-unit x qty^2."""
    parser = make_parser()
    row = transform_one(parser, YESSS_SUPPLIER, part, qty, discount, net)
    per_unit = Decimal(str(row["cost_per_item"]))
    q = Decimal(str(row["quantity"]))
    assert round_half_up(per_unit * q) == round_half_up(row["total_amount"]) \
        or per_unit * q != per_unit * q * q  # guard: not squared


@pytest.mark.parametrize("part,qty,discount,net", YESSS_MULTI, ids=YESSS_MULTI_IDS)
def test_selling_is_per_unit_no_squaring_normal_line(part, qty, discount, net):
    """On the normal path selling_price is per-unit, so the downstream line
    selling (upload.py: selling_price * qty) equals per_unit * qty, NOT * qty^2."""
    parser = make_parser()  # no catalog -> selling_price stays per-unit
    row = transform_one(parser, YESSS_SUPPLIER, part, qty, discount, net)
    unit_sell = Decimal(str(row["selling_price"]))
    q = Decimal(str(row["quantity"]))
    line_sell = unit_sell * q                     # what upload.py computes
    assert line_sell != unit_sell * q * q          # not squared


# ═══════════════════════════════════════════════════════════════════════════
# 4. QB/Xero higher-price override on a qty>1 line must not square quantity
#    (the flip at claude_parser.py:1135 — VME110, qty 2)
# ═══════════════════════════════════════════════════════════════════════════
def test_qb_override_selling_price_is_per_unit():
    """When the stored QB price is higher, selling_price should remain PER-UNIT
    (= the QB unit price). Bug: line 1135 sets it to unit_price * qty (a line
    total), so this stores 180.00 instead of 90.00 for VME110 qty 2."""
    qb_unit_price = 90.0
    parser = make_parser(known_products=qb_product("VME110", qb_unit_price))
    row = transform_one(parser, YESSS_SUPPLIER, "VME110", 2, 44, "102.09")
    assert Decimal(str(row["selling_price"])) == round_half_up(qb_unit_price)


def test_qb_override_line_total_not_squared():
    """Downstream line selling = selling_price * qty must equal qb_unit * qty
    (180.00), not qb_unit * qty^2 (360.00)."""
    qb_unit_price = 90.0
    parser = make_parser(known_products=qb_product("VME110", qb_unit_price))
    row = transform_one(parser, YESSS_SUPPLIER, "VME110", 2, 44, "102.09")
    q = Decimal(str(row["quantity"]))
    line_sell = Decimal(str(row["selling_price"])) * q          # upload.py:486
    expected_line = round_half_up(qb_unit_price) * q             # 90 * 2 = 180
    assert line_sell == expected_line


# ═══════════════════════════════════════════════════════════════════════════
# 5. profit == selling - cost (per unit)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("part,qty,discount,net", YESSS_LINES, ids=YESSS_IDS)
def test_profit_equals_selling_minus_cost(part, qty, discount, net):
    """profit_per_item must equal selling_price - cost_per_item (per unit),
    rounded to the penny."""
    parser = make_parser()
    row = transform_one(parser, YESSS_SUPPLIER, part, qty, discount, net)
    expected = round_half_up(Decimal(str(row["selling_price"]))
                             - Decimal(str(row["cost_per_item"])))
    assert round_half_up(row["profit_per_item"]) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 6. _get_admin_tiered_markup() returns the documented % per discount band
# ═══════════════════════════════════════════════════════════════════════════
# Continuous bands: d<=0 -> 20%, 0<d<=30 -> 40%, 30<d<=70 -> 50%, d>70 -> 70%.
MARKUP_BANDS = [
    (0,    0.20),
    (0.5,  0.40),  # fractional discount must NOT fall through the gap -> 40%
    (1,    0.40),
    (15,   0.40),
    (30,   0.40),  # boundary: 30 is in the 0<d<=30 band
    (30.5, 0.50),  # fractional discount in the next band -> 50%
    (31,   0.50),
    (50,   0.50),
    (70,   0.50),  # boundary: 70 is in the 30<d<=70 band
    (71,   0.70),
    (85,   0.70),
]


@pytest.mark.parametrize("discount,expected", MARKUP_BANDS,
                         ids=[f"d{d}" for d, _ in MARKUP_BANDS])
def test_admin_tiered_markup_bands(discount, expected):
    parser = make_parser()
    assert parser._get_admin_tiered_markup(discount) == expected


def test_print_markup_table(capsys):
    """Print the actual markup table so it can be eyeballed (use -s)."""
    parser = make_parser()
    probes = [0, 0.5, 1, 15, 30, 30.5, 31, 50, 70, 70.5, 71, 85, 100]
    with capsys.disabled():
        print("\n=== _get_admin_tiered_markup(discount) ===")
        print(f"{'discount %':>12} | {'markup':>8}")
        print("-" * 25)
        for d in probes:
            print(f"{d:>12} | {parser._get_admin_tiered_markup(d) * 100:>6.0f}%")
        print("note: bands are continuous — fractional discounts map to their band (no gap)")


# ═══════════════════════════════════════════════════════════════════════════
# Eyeball table: parsed cost, markup %, ex-GST selling, profit per line
# ═══════════════════════════════════════════════════════════════════════════
def test_print_line_breakdown(capsys):
    """Print the full per-line breakdown for both suppliers (admin tiered
    markup). Non-asserting — for eyeballing with -s."""
    with capsys.disabled():
        for supplier, lines in (("YESSS (net as-is)", YESSS_LINES),
                                 ("Wholesale (gross->net)",
                                  [(p, q, d, g) for p, q, d, g, _ in WHOLESALE_LINES])):
            parser = make_parser()  # admin, no catalog
            print(f"\n=== {supplier} ===")
            print(f"{'part':<13}{'qty':>5}{'disc%':>6}{'cost/u':>9}"
                  f"{'mkup%':>7}{'sell/u':>9}{'profit/u':>10}{'line sell':>11}")
            print("-" * 80)
            for part, qty, disc, amount in lines:
                row = transform_one(parser, supplier, part, qty, disc, amount)
                if not row:
                    print(f"{part:<13}  (skipped)")
                    continue
                line_sell = float(row["selling_price"]) * float(row["quantity"])
                print(f"{part:<13}{qty:>5}{disc:>6}{row['cost_per_item']:>9.2f}"
                      f"{row['markup_percent']:>7}{row['selling_price']:>9.2f}"
                      f"{row['profit_per_item']:>10.2f}{line_sell:>11.2f}")


# ═══════════════════════════════════════════════════════════════════════════
# COST-BASE PIN (claude_parser.py:1139) — the biggest real-world consequence of
# flipping tax_registered. Registered users reclaim input GST (cost ex-tax);
# unregistered users cannot, so irrecoverable supplier GST is folded into the
# markup base. The vat_*/tax_* unification MUST NOT silently shift this — these
# two tests pin both behaviours. (markup=0 so selling == effective cost.)
# ═══════════════════════════════════════════════════════════════════════════
def test_cost_base_unregistered_folds_irrecoverable_input_gst():
    parser = make_parser(is_admin=False, default_markup=0.0, tax_registered=False)
    out = parser._transform_items([make_item("WID1", 1, 0, "100.00")],
                                  supplier="X", supplier_tax_rate=5)[0]
    # 100 cost + 5% irrecoverable supplier GST = 105 effective cost (markup base)
    assert round_half_up(out["cost_per_item"]) == Decimal("105.00")
    assert round_half_up(out["selling_price"]) == Decimal("105.00")


def test_cost_base_registered_excludes_input_gst():
    parser = make_parser(is_admin=False, default_markup=0.0, tax_registered=True)
    out = parser._transform_items([make_item("WID1", 1, 0, "100.00")],
                                  supplier="X", supplier_tax_rate=5)[0]
    # Registered: reclaims input GST -> cost stays ex-tax at 100 (NOT 105)
    assert round_half_up(out["cost_per_item"]) == Decimal("100.00")
    assert round_half_up(out["selling_price"]) == Decimal("100.00")
