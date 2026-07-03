"""The single gate for which invoice lines are pushed to accounting software.

Soft-removed lines (``InvoiceItem.excluded``) must touch NEITHER the customer invoice / estimate /
quote NOR the product catalog, on BOTH QuickBooks and Xero. Every customer-facing provider sync
path selects its lines through ``get_syncable_line_items()`` so there is ONE exclusion gate, not one
per path per provider. Pairs with ``invoice_totals.recompute_invoice_totals`` (the header side): the
lines pushed here and the header totals are both derived from the same non-excluded set.

The supplier BILL (accounts payable) deliberately does NOT use this — a returned / soft-removed line
still appears on the supplier's paper invoice, so the Bill pushes all lines (see the QB/Xero
`sync_invoice_to_quickbooks` / `sync_invoice_to_bill` methods).
"""
from app.models.invoice import InvoiceItem


def get_syncable_line_items(invoice):
    """Non-excluded InvoiceItem rows for this invoice/quote, id-ordered for a stable push order."""
    return (InvoiceItem.query
            .filter_by(invoice_id=invoice.id, excluded=False)
            .order_by(InvoiceItem.id)
            .all())
