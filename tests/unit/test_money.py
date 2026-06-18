"""Unit tests for the shared money helper (app/utils/money.py)."""
from decimal import Decimal

from app.utils.money import money, to_decimal


def test_money_rounds_half_up_not_bankers():
    # Binary-float round(1.785, 2) gives 1.78 (banker's + float); money() is 1.79.
    assert money(Decimal('1.785')) == Decimal('1.79')
    assert money('1.785') == Decimal('1.79')


def test_money_line_net_rounds_up_exactly():
    # 13.40 * 0.225 = 3.015 exact in Decimal -> 3.02 (the WMPB2/28 case).
    assert money(Decimal('13.40') * (1 - Decimal('77.5') / 100)) == Decimal('3.02')


def test_money_per_unit_penny():
    # 7.14 * 0.25 = 1.785 -> 1.79 (the CMA240 case).
    assert money(Decimal('7.14') * Decimal('0.25')) == Decimal('1.79')


def test_money_none_and_symbols():
    assert money(None) == Decimal('0.00')
    assert money('') == Decimal('0.00')
    assert money('£1,234.567') == Decimal('1234.57')


def test_money_places_4_for_unit_rate():
    # Sub-penny per-metre rate keeps 4dp.
    assert money('0.20521', places=4) == Decimal('0.2052')


def test_to_decimal_passthrough_clean_and_none():
    assert to_decimal(Decimal('5')) == Decimal('5')
    assert to_decimal('5%') == Decimal('5')
    assert to_decimal(2.5) == Decimal('2.5')
    assert to_decimal('none') is None
    assert to_decimal(None) is None
    assert to_decimal('') is None
