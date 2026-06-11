"""
Invoice Arithmetic Validator
============================
Validates that AI-extracted invoice data is internally consistent BEFORE it
is stored or synced to QuickBooks/Xero.

Checks performed:
  1. Line items sum to the invoice net total (with rounding tolerance)
  2. Net + tax = gross total
  3. Tax amount is consistent with the stated tax rate
  4. Per-line: quantity x unit_price = line total (when unit_price present)
  5. Sanity checks: negatives, implausible tax rates, missing totals

Design notes:
  - Pure stdlib (Decimal) - no app imports, safe to unit test in isolation.
  - Distinguishes ERRORS (numbers don't add up - block/flag for review)
    from WARNINGS (suspicious but possibly fine - log and proceed).
  - Tolerances account for legitimate supplier rounding: each line can be
    off by a penny, so allowed drift scales with line count.

Usage:
    from app.services.invoice_validator import validate_invoice
    result = validate_invoice(invoice_data)
    if not result.is_valid:
        # flag for manual review, do NOT auto-sync
        ...
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

# Per-line rounding tolerance (suppliers round each line to the penny)
PER_LINE_TOLERANCE = Decimal("0.01")
# Minimum overall tolerance even for single-line invoices
BASE_TOLERANCE = Decimal("0.02")
# Tax rates considered "normal" for UK/Jersey suppliers (%, as Decimal)
PLAUSIBLE_TAX_RATES = [Decimal("0"), Decimal("5"), Decimal("20")]
# How far a stated rate may sit from a plausible rate before warning (%)
TAX_RATE_SLACK = Decimal("0.5")


def _to_decimal(value: Any) -> Optional[Decimal]:
    """Convert parser values (str/float/int/None/'None') to Decimal safely."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "none":
        return None
    s = s.replace(",", "").replace("£", "").replace("%", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _money(value: Decimal) -> Decimal:
    """Quantise to 2dp, banker-safe for invoices (round half up)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Computed figures, useful for logging/diagnostics
    computed_line_sum: Optional[Decimal] = None
    stated_net: Optional[Decimal] = None
    stated_tax: Optional[Decimal] = None
    stated_gross: Optional[Decimal] = None

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "computed_line_sum": (
                str(self.computed_line_sum)
                if self.computed_line_sum is not None
                else None
            ),
            "stated_net": str(self.stated_net) if self.stated_net is not None else None,
            "stated_tax": str(self.stated_tax) if self.stated_tax is not None else None,
            "stated_gross": (
                str(self.stated_gross) if self.stated_gross is not None else None
            ),
        }


def validate_invoice(invoice_data: Dict[str, Any]) -> ValidationResult:
    """
    Validate one extracted invoice dict (the raw AI extraction, i.e. the dict
    containing 'items', 'total_net_amount', 'tax_amount', 'total_inc_tax',
    'tax_rate' - the same keys claude_parser reads).

    Also accepts the post-transform keys ('total_ex_tax') as a fallback so it
    can be called at either stage of the pipeline.
    """
    result = ValidationResult()

    items = invoice_data.get("items") or []
    stated_net = _to_decimal(
        invoice_data.get("total_net_amount", invoice_data.get("total_ex_tax"))
    )
    stated_tax = _to_decimal(invoice_data.get("tax_amount"))
    stated_gross = _to_decimal(invoice_data.get("total_inc_tax"))
    tax_rate = _to_decimal(invoice_data.get("tax_rate"))

    result.stated_net = stated_net
    result.stated_tax = stated_tax
    result.stated_gross = stated_gross

    # ── Check 0: do we have anything to validate? ─────────────────────────
    if not items:
        result.add_error("Invoice has no line items")
        return result

    if stated_net is None and stated_gross is None:
        result.add_warning(
            "No invoice totals extracted (total_net_amount / total_inc_tax both "
            "missing) - arithmetic cannot be verified"
        )

    # ── Check 1: per-line arithmetic + sum of lines ───────────────────────
    line_sum = Decimal("0")
    usable_lines = 0
    for idx, item in enumerate(items, start=1):
        qty = _to_decimal(item.get("quantity"))
        line_total = _to_decimal(item.get("total_amount"))
        unit_price = _to_decimal(item.get("unit_price"))
        label = item.get("part_number") or item.get("description") or f"line {idx}"

        if line_total is None:
            result.add_warning(f"Line {idx} ({label}): missing total_amount")
            continue

        if line_total < 0:
            result.add_warning(
                f"Line {idx} ({label}): negative amount {line_total} - "
                "credit line on an invoice?"
            )

        usable_lines += 1
        line_sum += line_total

        # qty x unit price should reproduce the line total when both present
        if qty is not None and unit_price is not None and qty > 0:
            expected = _money(qty * unit_price)
            if (expected - line_total).copy_abs() > PER_LINE_TOLERANCE:
                result.add_error(
                    f"Line {idx} ({label}): {qty} x {unit_price} = {expected}, "
                    f"but extracted line total is {line_total}"
                )

        if qty is not None and qty < 0:
            result.add_warning(f"Line {idx} ({label}): negative quantity {qty}")

    result.computed_line_sum = _money(line_sum)

    # Overall tolerance scales with how many lines could each carry 1p drift
    tolerance = max(BASE_TOLERANCE, PER_LINE_TOLERANCE * max(usable_lines, 1))

    # ── Check 2: lines sum to net total ───────────────────────────────────
    if stated_net is not None and usable_lines > 0:
        diff = (result.computed_line_sum - stated_net).copy_abs()
        if diff > tolerance:
            result.add_error(
                f"Line items sum to {result.computed_line_sum} but invoice net "
                f"total is {stated_net} (difference {_money(diff)}, "
                f"tolerance {tolerance})"
            )

    # ── Check 3: net + tax = gross ────────────────────────────────────────
    if stated_net is not None and stated_tax is not None and stated_gross is not None:
        expected_gross = _money(stated_net + stated_tax)
        diff = (expected_gross - stated_gross).copy_abs()
        if diff > BASE_TOLERANCE:
            result.add_error(
                f"Net {stated_net} + tax {stated_tax} = {expected_gross}, "
                f"but invoice gross total is {stated_gross}"
            )

    # ── Check 4: tax amount consistent with tax rate ──────────────────────
    if (
        stated_net is not None
        and stated_tax is not None
        and tax_rate is not None
        and tax_rate > 0
        and stated_net > 0
    ):
        expected_tax = _money(stated_net * tax_rate / Decimal("100"))
        # Tax rounding rules vary by supplier (line-level vs invoice-level),
        # so allow a slightly looser tolerance here.
        tax_tolerance = max(tolerance, Decimal("0.05"))
        diff = (expected_tax - stated_tax).copy_abs()
        if diff > tax_tolerance:
            result.add_error(
                f"Tax of {stated_tax} inconsistent with rate {tax_rate}% on net "
                f"{stated_net} (expected ~{expected_tax})"
            )

    # ── Check 5: sanity ───────────────────────────────────────────────────
    if tax_rate is not None:
        if tax_rate < 0 or tax_rate > Decimal("30"):
            result.add_error(f"Implausible tax rate extracted: {tax_rate}%")
        elif not any(
            (tax_rate - r).copy_abs() <= TAX_RATE_SLACK for r in PLAUSIBLE_TAX_RATES
        ):
            result.add_warning(
                f"Unusual tax rate {tax_rate}% (expected 0%, 5% or 20%) - "
                "verify supplier invoice"
            )

    if stated_gross is not None and stated_net is not None and stated_gross < stated_net:
        result.add_error(
            f"Gross total {stated_gross} is less than net total {stated_net}"
        )

    return result


def validate_parse_result(parse_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convenience wrapper for the dict returned by ClaudeParser
    (single or consolidated). Returns a list of result dicts, one per invoice:
      [{"invoice_number": ..., "validation": {...}}, ...]
    """
    out: List[Dict[str, Any]] = []
    if not parse_result.get("success"):
        return out

    invoices = (
        parse_result.get("invoices")
        if parse_result.get("consolidated")
        else [parse_result]
    )
    for inv in invoices or []:
        res = validate_invoice(inv)
        out.append(
            {
                "invoice_number": inv.get("invoice_number"),
                "supplier": inv.get("supplier"),
                "validation": res.to_dict(),
            }
        )
    return out
