"""Phase 1: QB/Xero read-back price must not exceed the supplier counter price.

Replaces the old `>10x calc` guard with a list-price ceiling (max(list, calc)).
Proves a contaminated read-back (QB >> list) is clipped to calc, while a legit
at/below-counter read-back (high markup but <= list) is PRESERVED — the
false-positive risk we most care about.

Loaded by file path (no `app`/Flask/API-key import), mirroring test_claude_parser_calc.py.
"""
import importlib.util
import logging
from pathlib import Path

_PARSER_PATH = Path(__file__).resolve().parents[2] / "app" / "parsers" / "claude_parser.py"
_spec = importlib.util.spec_from_file_location("claude_parser_rb", _PARSER_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ClaudeInvoiceParser = _mod.ClaudeInvoiceParser

WHOLESALE = "Wholesale Electrics"


def make_parser(known_products=None, *, is_admin=True, tax_registered=True, tax_rate=0.0):
    p = ClaudeInvoiceParser.__new__(ClaudeInvoiceParser)
    p.logger = logging.getLogger("test_qb_readback")
    p._known_products_cache = dict(known_products or {})  # not None => offline, no DB
    p.user_markup_settings = {"is_admin": is_admin, "default_markup": 50.0,
                              "tax_registered": tax_registered, "tax_rate": tax_rate}
    return p


def item(part, qty, discount, amount, orig=0):
    return {"part_number": part, "description": part, "quantity": qty,
            "discount": str(discount), "total_amount": str(amount), "original_unit_price": orig}


def qb(part, price):
    return {part.upper(): {"name": part, "sku": part, "source": "quickbooks", "sales_price": price}}


def one(parser, it):
    out = parser._transform_items([it], supplier=WHOLESALE)
    return out[0] if out else None


# ── contaminated read-back (QB >> list) → clip to calc (the IN391270 / PX6242YH16.0GRY bug) ──
def test_contaminated_readback_clips_to_calc():
    # non-registered + 5% fold: cost 5.25 -> effective 5.51, calc 6.61. QB catalog 47.82, list 5.25.
    p = make_parser(qb("PX6242YH16.0GRY", 47.82), tax_registered=False, tax_rate=5.0)
    r = one(p, item("PX6242YH16.0GRY", 10, 0, "52.50", orig=5.25))
    assert round(r["cost_per_item"], 2) == 5.51
    assert round(r["calculated_selling_price"], 2) == 6.61
    assert round(r["selling_price"], 2) == 6.61           # clipped to calc...
    assert round(r["selling_price"], 2) != 47.82          # ...NOT the contaminated 47.82
    assert r["markup_percent"] <= 25                       # ~20%, not 810%


# ── legit at-counter read-back (QB <= list, high markup) → PRESERVED (false-positive guard) ──
def test_legit_at_counter_readback_preserved():
    # cost 0.95, calc 1.14, counter/list 9.00, QB 8.50 (<= list) — high margin but legitimate.
    p = make_parser(qb("YDTGM20B", 8.50), tax_registered=True, tax_rate=0.0)
    r = one(p, item("YDTGM20B", 1, 0, "0.95", orig=9.00))
    assert round(r["calculated_selling_price"], 2) == 1.14
    assert round(r["selling_price"], 2) == 8.50            # preserved, NOT clipped to calc
    assert round(r["selling_price"], 2) != round(r["calculated_selling_price"], 2)


# ── no list price: modest read-back preserved, absurd falls back to calc ──
def test_nolist_modest_preserved():
    p = make_parser(qb("NOLIST_MODEST", 25.0), tax_registered=True, tax_rate=0.0)
    r = one(p, item("NOLIST_MODEST", 1, 0, "10.00", orig=0))   # cost 10, calc 12, no list
    assert round(r["calculated_selling_price"], 2) == 12.00
    assert round(r["selling_price"], 2) == 25.00               # 2.5x cost, under 5x -> kept


def test_nolist_absurd_falls_to_calc():
    p = make_parser(qb("NOLIST_ABSURD", 90.0), tax_registered=True, tax_rate=0.0)
    r = one(p, item("NOLIST_ABSURD", 1, 0, "10.00", orig=0))   # cost 10, calc 12, QB 90 (>5x)
    assert round(r["calculated_selling_price"], 2) == 12.00
    assert round(r["selling_price"], 2) == 12.00               # no list + absurd -> calc


# ── clean line (no catalog entry) is unaffected ──
def test_clean_line_unaffected():
    p = make_parser(tax_registered=True, tax_rate=0.0)         # empty catalog
    r = one(p, item("CLEAN1", 1, 0, "10.00", orig=12.00))
    assert round(r["selling_price"], 2) == round(r["calculated_selling_price"], 2) == 12.00
