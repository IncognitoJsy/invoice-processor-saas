"""The single gate for which invoice lines are pushed to accounting software.

Two kinds of line must touch NEITHER the customer invoice / estimate / quote NOR the product
catalog, on BOTH QuickBooks and Xero:

  1. Soft-removed lines (``InvoiceItem.excluded``) — the user removed a returned line before sync.
  2. DEDUCTION lines (``total_amount < 0``) — a bundled component the supplier removed from a kit
     and posted as a negative line (e.g. qty -1 / -33.00). These are retained COST-ONLY: they stay
     in the arithmetic reconciliation and on the supplier Bill (so the invoice keeps tying to the
     supplier net), but they are NOT billed to the customer — the customer sees only the positive,
     marked-up lines. Detection is sign-derived (no column/flag), matching the parser.

Every customer-facing provider sync path selects its lines through ``get_syncable_line_items()`` so
there is ONE gate, not one per path per provider.

Deduction lines are deliberately NOT filtered out of ``invoice_totals.recompute_invoice_totals``
(the header side, which has its own non-excluded filter) — the negative amount MUST stay in the
header net so the invoice keeps reconciling. This gate governs only what is PUSHED, never the totals
or validation. The two stay consistent on the customer side because a deduction's ``selling_price``
is 0, so it contributes nothing to ``total_selling`` even though it counts in ``total_cost``/net.

The supplier BILL (accounts payable) deliberately does NOT use this gate — a returned / soft-removed
line AND a supplier deduction both appear on the supplier's paper invoice, so the Bill pushes all
lines (see the QB/Xero `sync_invoice_to_quickbooks` / `sync_invoice_to_bill` methods).
"""
from app.models.invoice import InvoiceItem


def is_deduction_line(item):
    """True for a negative-amount supplier deduction line (sign-derived, no flag)."""
    return item.total_amount is not None and item.total_amount < 0


def get_syncable_line_items(invoice):
    """Line items pushed to a provider: non-excluded AND non-deduction, id-ordered for a stable push
    order. Excludes soft-removed lines (``excluded``) and deduction lines (``total_amount < 0``) —
    the latter are cost-only and never billed to the customer, on BOTH QB and Xero."""
    return (InvoiceItem.query
            .filter_by(invoice_id=invoice.id, excluded=False)
            .filter(InvoiceItem.total_amount >= 0)
            .order_by(InvoiceItem.id)
            .all())
