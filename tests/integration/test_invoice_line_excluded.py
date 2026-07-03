"""Phase 1 of "remove a returned line / edit qty before sync": the `excluded` soft-remove flag and
the header-totals recompute (app/services/invoice_totals.recompute_invoice_totals).

The whole RISK of the feature is the totals guard: if a line is removed but the header net still
reflects the original supplier figure, the line-sum no longer matches and a re-validation would
reject. These tests prove the recompute keeps the invariants true, so an already-clean invoice
stays clean — and prove (negative control) that WITHOUT the recompute it would fail.

Bridges the ORM recompute to the validator the same way tests/test_invoice_reconciler.py does:
build the validator's extraction dict from the (recomputed) invoice + its active lines and assert
validate_invoice(...).is_valid. The real sync guard reads the FROZEN validation_errors snapshot
and never re-runs the validator (parse-time only) — re-validating here proves the invariant holds.
"""
from decimal import Decimal

from app.models.user import User
from app.models.invoice import Invoice, InvoiceItem
from app.services.invoice_totals import recompute_invoice_totals
from app.services.invoice_validator import validate_invoice


def _clean_invoice(db, user):
    """3 lines, 5% GST, line-sum ties the stated net → a clean, validator-passing invoice.

    A(qty2 cost10 →20), B(qty1 cost30 →30), C(qty1 cost50 →50): net 100, tax 5, gross 105.
    selling 14*2 + 40 + 65 = 133.
    """
    inv = Invoice(
        user_id=user.id, supplier_name='YESSS Electrical', status='completed', invoice_number='EX-1',
        supplier_tax_rate=Decimal('5.00'), supplier_tax_amount=Decimal('5.00'),
        total_cost=Decimal('100.00'), total_ex_tax=Decimal('100.00'), total_inc_tax=Decimal('105.00'),
        total_selling=Decimal('133.00'), total_profit=Decimal('33.00'), items_count=3,
        validation_errors=None,
    )
    db.session.add(inv); db.session.flush()
    rows = [
        dict(part_number='A', quantity=Decimal('2'), cost_per_item=Decimal('10'), total_amount=Decimal('20'),
             selling_price=Decimal('14'), profit_per_item=Decimal('4')),
        dict(part_number='B', quantity=Decimal('1'), cost_per_item=Decimal('30'), total_amount=Decimal('30'),
             selling_price=Decimal('40'), profit_per_item=Decimal('10')),
        dict(part_number='C', quantity=Decimal('1'), cost_per_item=Decimal('50'), total_amount=Decimal('50'),
             selling_price=Decimal('65'), profit_per_item=Decimal('15')),
    ]
    items = {}
    for r in rows:
        it = InvoiceItem(invoice_id=inv.id, description=r['part_number'], **r)
        db.session.add(it); items[r['part_number']] = it
    db.session.commit()
    return inv, items


def _validator_payload(inv):
    """Extraction dict the validator operates on, built from the invoice's NON-excluded lines."""
    active = [i for i in inv.items if not i.excluded]
    return {
        'items': [
            {'quantity': float(i.quantity), 'unit_price': float(i.cost_per_item),
             'total_amount': float(i.total_amount)}
            for i in active
        ],
        'total_ex_tax': float(inv.total_ex_tax),
        'tax_amount': float(inv.supplier_tax_amount),
        'total_inc_tax': float(inv.total_inc_tax),
        'tax_rate': float(inv.supplier_tax_rate),
    }


def test_default_false_and_exposed(app, db, user):
    inv, items = _clean_invoice(db, user)
    it = db.session.get(InvoiceItem, items['A'].id)
    assert it.excluded is False                      # server_default / model default
    assert it.to_dict()['excluded'] is False         # exposed to the UI


def test_baseline_invoice_is_clean(app, db, user):
    """Sanity: the fixture passes the validator before any edit."""
    inv, _ = _clean_invoice(db, user)
    assert validate_invoice(_validator_payload(inv)).is_valid


def test_exclude_line_drops_header_and_guard_passes(app, db, user):
    """THE feature-risk test: exclude a line → header totals drop to match the remaining lines →
    the totals validation PASSES (no line-sum-vs-net mismatch)."""
    inv, items = _clean_invoice(db, user)

    # Soft-remove line C (£50 net). Remaining A+B: net 50, tax 2.50, gross 52.50; selling 68.
    items['C'].excluded = True
    db.session.commit()

    recompute_invoice_totals(inv)
    db.session.commit()

    assert inv.total_cost == Decimal('50.00')
    assert inv.total_ex_tax == Decimal('50.00')
    assert inv.supplier_tax_amount == Decimal('2.50')     # 50 * 5%
    assert inv.total_inc_tax == Decimal('52.50')          # net + tax
    assert inv.total_selling == Decimal('68.00')          # 14*2 + 40
    assert inv.total_profit == Decimal('18.00')           # 68 - 50
    assert inv.items_count == 2

    # The guard now passes: line-sum (50) == stated net (50), net+tax==gross, tax==rate*net.
    assert validate_invoice(_validator_payload(inv)).is_valid

    # And an already-clean invoice STAYS clean: the validator never re-ran, so no new flag.
    assert inv.validation_errors is None


def test_without_recompute_the_guard_would_reject(app, db, user):
    """Negative control — proves the recompute is load-bearing, not incidental.

    Exclude the line but SKIP the recompute: the header still says net 100 while the remaining
    lines sum to 50, so the validator rejects on the line-sum mismatch (exactly what would slip
    through if we let users edit lines without recomputing)."""
    inv, items = _clean_invoice(db, user)
    items['C'].excluded = True
    db.session.commit()
    # No recompute_invoice_totals() call — stale header (100/5/105) vs active lines summing to 50.

    result = validate_invoice(_validator_payload(inv))
    assert not result.is_valid
    assert any('sum to' in e for e in result.errors)      # "Line items sum to 50 but ... net total is 100"


def test_recompute_reflects_quantity_change(app, db, user):
    """The recompute is driven by each line's total_amount, so a quantity reduction (Phase 3 route
    will set total_amount = cost * new_qty) flows straight through to the header + stays valid."""
    inv, items = _clean_invoice(db, user)

    # Simulate reducing line A from qty 2 → 1: total_amount 20 → 10 (cost 10 * 1).
    items['A'].quantity = Decimal('1')
    items['A'].total_amount = Decimal('10')
    db.session.commit()

    recompute_invoice_totals(inv)
    db.session.commit()

    assert inv.total_cost == Decimal('90.00')             # 10 + 30 + 50
    assert inv.supplier_tax_amount == Decimal('4.50')     # 90 * 5%
    assert inv.total_inc_tax == Decimal('94.50')
    assert validate_invoice(_validator_payload(inv)).is_valid
