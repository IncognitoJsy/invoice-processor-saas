"""Recompute an invoice's header financial totals from its line items.

Used when a line is soft-removed (``InvoiceItem.excluded``) or its quantity changes before sync.
The LINE is the authority (same philosophy as invoice_reconciler / save_invoice_to_db): the header
net is the sum of the NON-excluded per-line ``total_amount``, and tax is re-derived from the stored
supplier rate so the invariants the arithmetic validator checks stay true by construction —

    computed_line_sum == stated_net        (validator Check 2)
    stated_net + stated_tax == stated_gross (validator Check 3)
    stated_tax == stated_net * rate         (validator Check 4)

Keeping those true means an already-clean invoice STILL passes if anything re-validates it. This
function itself NEVER runs the validator and NEVER writes ``validation_errors`` — validation is
parse-time only (app/web/upload.py), so an edit cannot newly flag a clean invoice.

Pure w.r.t. I/O: it mutates the passed Invoice in place and does not commit; the caller commits.
"""
from decimal import Decimal

from app.utils.money import money, to_decimal


def recompute_invoice_totals(invoice):
    """Recompute header totals from the invoice's non-excluded lines. Returns the invoice.

    Recomputes (model column ← meaning):
      total_cost / total_ex_tax ← supplier ex-tax net (Σ non-excluded line total_amount)
      supplier_tax_amount       ← net × supplier_tax_rate  (0 when unregistered / no rate)
      total_inc_tax             ← net + tax  (gross)
      total_selling             ← Σ money(selling_price × quantity)
      total_profit              ← total_selling − total_cost (line-authority, penny-exact)
      average_markup, items_count
    Deliberately does NOT touch supplier_tax_rate (owned by extraction/picker) or any
    price_overridden line's selling_price (that override is authoritative — see InvoiceItem).
    """
    active = [i for i in invoice.items if not getattr(i, 'excluded', False)]

    line_costs = [money(i.total_amount or 0) for i in active]
    line_sellings = [
        money((to_decimal(i.selling_price) or Decimal('0')) * (to_decimal(i.quantity) or Decimal('0')))
        for i in active
    ]

    net = money(sum(line_costs, Decimal('0')))
    selling = money(sum(line_sellings, Decimal('0')))
    profit = money(sum((s - c for s, c in zip(line_sellings, line_costs)), Decimal('0')))

    rate = to_decimal(invoice.supplier_tax_rate) or Decimal('0')
    tax = money(net * rate / Decimal('100')) if rate > 0 else money(Decimal('0'))

    invoice.total_cost = net
    invoice.total_ex_tax = net
    invoice.supplier_tax_amount = tax
    invoice.total_inc_tax = money(net + tax)
    invoice.total_selling = selling
    invoice.total_profit = profit
    invoice.items_count = len(active)
    if net > 0:
        invoice.average_markup = money(min(((selling - net) / net) * Decimal('100'), Decimal('999.99')))

    return invoice
