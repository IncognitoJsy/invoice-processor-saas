"""
Tests for app/services/invoice_validator.py

Run from repo root:
    pytest tests/unit/test_invoice_validator.py -v
"""

import importlib.util
from pathlib import Path

# Load the validator module directly by file path. This avoids importing the
# `app` package (which initialises Flask/SQLAlchemy), so these tests run fast
# and work even in environments without the app's dependencies installed.
_VALIDATOR_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "services" / "invoice_validator.py"
)
_spec = importlib.util.spec_from_file_location("invoice_validator", _VALIDATOR_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

validate_invoice = _mod.validate_invoice
validate_parse_result = _mod.validate_parse_result


def make_invoice(**overrides):
    """A clean, internally-consistent 20% VAT invoice."""
    inv = {
        "invoice_number": "JER123456",
        "supplier": "CEF",
        "items": [
            {
                "part_number": "6242Y2.5",
                "description": "2.5mm Twin & Earth 100m",
                "quantity": 2,
                "unit_price": 45.50,
                "total_amount": 91.00,
            },
            {
                "part_number": "MK-K2747",
                "description": "MK 13A Double Socket",
                "quantity": 10,
                "unit_price": 3.20,
                "total_amount": 32.00,
            },
        ],
        "total_net_amount": 123.00,
        "tax_rate": 20,
        "tax_amount": 24.60,
        "total_inc_tax": 147.60,
    }
    inv.update(overrides)
    return inv


# ── Happy path ──────────────────────────────────────────────────────────────

def test_clean_invoice_passes():
    result = validate_invoice(make_invoice())
    assert result.is_valid, result.errors
    assert result.errors == []


def test_string_numbers_with_currency_symbols_pass():
    inv = make_invoice(
        total_net_amount="£123.00",
        tax_amount="24.60",
        total_inc_tax="147.60",
    )
    result = validate_invoice(inv)
    assert result.is_valid, result.errors


def test_penny_rounding_within_tolerance_passes():
    # Each line may legitimately be off by a penny vs net total
    inv = make_invoice(total_net_amount=123.02)  # 2 lines -> 2p tolerance
    result = validate_invoice(inv)
    assert result.is_valid, result.errors


# ── Arithmetic failures the AI must not slip past ──────────────────────────

def test_line_sum_mismatch_fails():
    inv = make_invoice(total_net_amount=150.00)  # lines actually sum to 123
    result = validate_invoice(inv)
    assert not result.is_valid
    assert any("sum to" in e for e in result.errors)


def test_net_plus_tax_not_equal_gross_fails():
    inv = make_invoice(total_inc_tax=160.00)  # should be 147.60
    result = validate_invoice(inv)
    assert not result.is_valid
    assert any("gross" in e.lower() for e in result.errors)


def test_tax_inconsistent_with_rate_fails():
    inv = make_invoice(tax_amount=10.00, total_inc_tax=133.00)  # 20% of 123 = 24.60
    result = validate_invoice(inv)
    assert not result.is_valid
    assert any("inconsistent with rate" in e for e in result.errors)


def test_bad_line_extension_fails():
    inv = make_invoice()
    inv["items"][0]["total_amount"] = 9.10  # 2 x 45.50 should be 91.00
    # keep stated totals matching the bad line so ONLY the line check fires
    inv["total_net_amount"] = 41.10
    inv["tax_amount"] = 8.22
    inv["total_inc_tax"] = 49.32
    result = validate_invoice(inv)
    assert not result.is_valid
    assert any("line" in e.lower() and "91.00" in e for e in result.errors)


def test_gross_less_than_net_fails():
    inv = make_invoice(total_inc_tax=100.00, tax_amount=-23.00)
    result = validate_invoice(inv)
    assert not result.is_valid


def test_implausible_tax_rate_fails():
    inv = make_invoice(tax_rate=85)
    result = validate_invoice(inv)
    assert not result.is_valid
    assert any("Implausible tax rate" in e for e in result.errors)


# ── Warnings (suspicious, not blocking) ─────────────────────────────────────

def test_no_totals_warns_but_does_not_fail():
    inv = make_invoice()
    del inv["total_net_amount"]
    del inv["total_inc_tax"]
    del inv["tax_amount"]
    result = validate_invoice(inv)
    assert result.is_valid
    assert any("cannot be verified" in w for w in result.warnings)


def test_unusual_but_possible_tax_rate_warns():
    inv = make_invoice(tax_rate=17.5, tax_amount=21.53, total_inc_tax=144.53)
    result = validate_invoice(inv)
    assert result.is_valid, result.errors
    assert any("Unusual tax rate" in w for w in result.warnings)


def test_negative_line_warns():
    inv = make_invoice()
    inv["items"].append(
        {"description": "Returned goods", "quantity": 1, "total_amount": -10.00}
    )
    inv["total_net_amount"] = 113.00
    inv["tax_amount"] = 22.60
    inv["total_inc_tax"] = 135.60
    result = validate_invoice(inv)
    assert any("negative amount" in w for w in result.warnings)


# ── Edge cases ──────────────────────────────────────────────────────────────

def test_empty_items_is_error():
    result = validate_invoice({"items": [], "total_net_amount": 100})
    assert not result.is_valid


def test_none_string_values_handled():
    inv = make_invoice(tax_amount="None", tax_rate="None")
    result = validate_invoice(inv)
    # Can't verify tax, but shouldn't crash or false-fail
    assert isinstance(result.is_valid, bool)


def test_zero_rated_invoice_passes():
    inv = make_invoice(tax_rate=0, tax_amount=0, total_inc_tax=123.00)
    result = validate_invoice(inv)
    assert result.is_valid, result.errors


# ── Wrapper for full parser results ────────────────────────────────────────

def test_validate_parse_result_single():
    parse_result = {"success": True, "consolidated": False, **make_invoice()}
    out = validate_parse_result(parse_result)
    assert len(out) == 1
    assert out[0]["validation"]["is_valid"] is True


def test_validate_parse_result_consolidated():
    good = make_invoice()
    bad = make_invoice(total_net_amount=999.99, invoice_number="JER999")
    parse_result = {"success": True, "consolidated": True, "invoices": [good, bad]}
    out = validate_parse_result(parse_result)
    assert len(out) == 2
    assert out[0]["validation"]["is_valid"] is True
    assert out[1]["validation"]["is_valid"] is False


def test_validate_parse_result_failed_parse_returns_empty():
    assert validate_parse_result({"success": False, "error": "boom"}) == []
