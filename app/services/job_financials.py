"""The single source of truth for a job's financials — used by BOTH the live job view and the
completion snapshot, so the two can never diverge.

Design decisions (Phase 1):
  * materials_sold is MODE-AGNOSTIC: Σ money(selling_price × quantity) over the non-excluded lines of
    the supplier invoices attached to the job. It does NOT depend on a CustomerInvoice existing, so it
    works identically for sync-mode and full-suite users. materials_cost = Σ money(total_amount)
    (line cost, incl. negative deduction lines); materials_profit = sold − cost.
  * labour_* come from labour_entry, whose pay/charge/employer-contribution rates are snapshotted per
    row at log time — so historical figures are already immune to later pay-rises; the completion
    snapshot then freezes the aggregate + per-employee breakdown so they survive row edits/deletes.
  * direct_costs_total is a Phase 2 hook (always 0 for now). overall_profit accounts for it from the
    start: overall_profit = materials_profit + labour_profit − direct_costs_total.

All money is Decimal via money(), 2dp ROUND_HALF_UP.
"""
from decimal import Decimal

from app.utils.money import money, to_decimal


def compute_job_financials(job):
    """Return a dict of frozen-shape figures for ``job`` (a JobCard). Pure read; no commit."""
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.employee import LabourEntry

    # --- Materials: over non-excluded lines of attached supplier invoices ---
    invoice_ids = [row.id for row in Invoice.query.filter_by(job_card_id=job.id).with_entities(Invoice.id).all()]
    mat_cost = Decimal('0')
    mat_sold = Decimal('0')
    if invoice_ids:
        items = (InvoiceItem.query
                 .filter(InvoiceItem.invoice_id.in_(invoice_ids), InvoiceItem.excluded == False)  # noqa: E712
                 .all())
        for it in items:
            mat_cost += money(it.total_amount or 0)
            qty = to_decimal(it.quantity) or Decimal('0')
            unit = to_decimal(it.selling_price) or Decimal('0')
            mat_sold += money(unit * qty)
    mat_cost = money(mat_cost)
    mat_sold = money(mat_sold)
    mat_profit = money(mat_sold - mat_cost)

    # --- Labour: from labour_entry (rates already snapshotted per row), excluding void ---
    entries = (LabourEntry.query
               .filter_by(job_card_id=job.id)
               .filter(LabourEntry.status != 'void')
               .all())
    lab_hours = Decimal('0')
    lab_cost = Decimal('0')
    lab_charged = Decimal('0')
    breakdown = {}
    for e in entries:
        hrs = to_decimal(e.hours) or Decimal('0')
        pay = to_decimal(e.pay_rate) or Decimal('0')
        charge = to_decimal(e.charge_out_rate) or Decimal('0')
        contrib = to_decimal(e.employer_contribution_rate)
        if contrib is None:
            contrib = Decimal('6.5')
        true_cost_hr = pay * (Decimal('1') + contrib / Decimal('100'))
        cost = money(hrs * true_cost_hr)
        charged = money(hrs * charge)
        lab_hours += hrs
        lab_cost += cost
        lab_charged += charged

        key = e.employee_id
        row = breakdown.get(key)
        if row is None:
            row = {
                'employee_id': e.employee_id,
                'name': (e.employee.display_name if e.employee else None),
                'pay_rate': float(pay), 'charge_out_rate': float(charge),
                'employer_contribution_rate': float(contrib),
                'hours': Decimal('0'), 'cost': Decimal('0'), 'charged': Decimal('0'),
            }
            breakdown[key] = row
        row['hours'] += hrs
        row['cost'] += cost
        row['charged'] += charged

    lab_hours = money(lab_hours)
    lab_cost = money(lab_cost)
    lab_charged = money(lab_charged)
    lab_profit = money(lab_charged - lab_cost)

    # Freeze per-employee detail (floats for JSON; totals already penny-exact in Decimal above).
    labour_breakdown = []
    for row in breakdown.values():
        labour_breakdown.append({
            'employee_id': row['employee_id'], 'name': row['name'],
            'pay_rate': row['pay_rate'], 'charge_out_rate': row['charge_out_rate'],
            'employer_contribution_rate': row['employer_contribution_rate'],
            'hours': float(money(row['hours'])),
            'cost': float(money(row['cost'])), 'charged': float(money(row['charged'])),
        })

    direct = money(Decimal('0'))  # Phase 2 hook
    overall = money(mat_profit + lab_profit - direct)

    return {
        'materials_cost': mat_cost, 'materials_sold': mat_sold, 'materials_profit': mat_profit,
        'labour_hours': lab_hours, 'labour_cost': lab_cost, 'labour_charged': lab_charged,
        'labour_profit': lab_profit, 'direct_costs_total': direct, 'overall_profit': overall,
        'labour_breakdown': labour_breakdown,
    }
