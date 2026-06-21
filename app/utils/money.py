"""Money helpers — the single place money is converted to Decimal and rounded.

Rule of thumb: do all money arithmetic in Decimal, round only with money(), and
downcast to float only at true edges (DB writes via Decimal(str(...)), JSON
responses, and QB/Xero API payloads via float(money(...))).
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional


def to_decimal(value: Any) -> Optional[Decimal]:
    """Convert str/float/int/Decimal/None/'None'/'£1,234.50'/'5%' to Decimal.

    Returns None when the value is missing or unparseable (callers decide the
    default). Strips thousands separators, currency and percent symbols.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if s == "" or s.lower() == "none":
        return None
    s = s.replace(",", "").replace("£", "").replace("%", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def money(value: Any, places: int = 2) -> Decimal:
    """THE one place money is rounded: quantise to `places` dp, ROUND_HALF_UP.

    Accepts a Decimal or anything to_decimal() handles. None / unparseable -> 0.
    Default is 2dp (currency); places=4 is used only for sub-penny unit rates
    (e.g. per-metre cable cost).
    """
    d = value if isinstance(value, Decimal) else to_decimal(value)
    if d is None:
        d = Decimal("0")
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
