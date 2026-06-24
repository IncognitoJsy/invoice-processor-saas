"""Cross-reconciliation of invoice-level totals, upstream of the arithmetic validator.

The LINE is the authority. The post-discount net = the sum of the per-line discounted totals
(``total_amount``). We only trust that net once an INDEPENDENT stated total confirms it:

  * ``gross_minus_tax``       = total_inc_tax - tax_amount
  * ``goods_minus_settlement`` = goods_value - item_settlement  (settlement-format invoices)

Tie-out rule (fail-closed):

  1. The line-sum anchor MUST be present (there must be usable line items), AND
  2. it MUST agree, within the validator's own tolerance, with at least ONE independent
     stated anchor.

Header anchors agreeing with *each other* but NOT backed by the line-sum do NOT tie — the lines
are the authority and headers only confirm them. When we tie, the canonical net is the line-sum
(never a header figure). When we don't, we change NOTHING and let the validator block exactly as
today. This never invents a passing net for a genuinely inconsistent invoice.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.utils.money import money, to_decimal
# Reuse the validator's own tolerance so reconcile and validate agree by construction.
from app.services.invoice_validator import BASE_TOLERANCE, PER_LINE_TOLERANCE


@dataclass
class ReconcileResult:
    tied: bool
    canonical_net: Optional[Decimal] = None
    corrected_from: Optional[Decimal] = None      # AI's stated net, if we overrode a mislabel
    anchors: Dict[str, Decimal] = field(default_factory=dict)
    agreeing: List[str] = field(default_factory=list)  # stated anchors that confirmed the line-sum
    reason: str = ""


def reconcile_totals(invoice_data: Dict[str, Any]) -> ReconcileResult:
    """Pick the canonical post-discount net iff the line-sum is confirmed by a stated total.

    Pure and side-effect-free: the caller decides whether to apply ``canonical_net``.
    """
    items = invoice_data.get("items") or []
    usable = [i for i in items if to_decimal(i.get("total_amount")) is not None]
    tol = max(BASE_TOLERANCE, PER_LINE_TOLERANCE * max(len(usable), 1))

    gross = to_decimal(invoice_data.get("total_inc_tax"))
    tax = to_decimal(invoice_data.get("tax_amount"))
    goods = to_decimal(invoice_data.get("goods_value"))
    settlement = to_decimal(invoice_data.get("item_settlement"))
    stated_net = to_decimal(invoice_data.get("total_ex_tax"))

    # Independent stated anchors (header-derived) — used only to CONFIRM the line-sum.
    header_anchors: Dict[str, Decimal] = {}
    if gross is not None and tax is not None:
        header_anchors["gross_minus_tax"] = money(gross - tax)
    if goods is not None and settlement is not None:
        header_anchors["goods_minus_settlement"] = money(goods - settlement)

    # (1) Line-sum anchor is mandatory — the lines are the authority.
    if not usable:
        return ReconcileResult(
            False, anchors=dict(header_anchors),
            reason="line-sum anchor absent (no usable line items) — cannot reconcile",
        )
    net_lines = money(sum((money(i.get("total_amount") or 0) for i in usable), Decimal("0")))
    anchors: Dict[str, Decimal] = {"lines": net_lines, **header_anchors}

    # Need at least one independent stated total to confirm against.
    if not header_anchors:
        return ReconcileResult(
            False, anchors=anchors,
            reason="no independent stated total to confirm the line-sum",
        )

    # (2) Line-sum must agree with at least one independent stated anchor.
    agreeing = [k for k, v in header_anchors.items() if (v - net_lines).copy_abs() <= tol]
    if not agreeing:
        return ReconcileResult(
            False, anchors=anchors,
            reason=(
                f"line-sum {net_lines} not confirmed by any stated total "
                f"({header_anchors}) within tolerance {tol}"
            ),
        )

    # Confirmed: the line-sum is the canonical net (never a header figure).
    corrected = stated_net is None or (stated_net - net_lines).copy_abs() > tol
    return ReconcileResult(
        True,
        canonical_net=net_lines,
        corrected_from=(stated_net if corrected else None),
        anchors=anchors,
        agreeing=agreeing,
    )
