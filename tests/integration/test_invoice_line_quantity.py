"""Phase 3: edit a line's quantity before sync (unsynced invoices only).

Quantity is not "total = qty x unit": cost_per_item / selling_price are stored as per-unit RATES
(per-metre on the 305m cable conversion; tax-inclusive for non-registered users) on a different
basis than the ex-tax total_amount. The route scales the ex-tax total_amount proportionally and
leaves the per-unit rates untouched, then recomputes the header via the shared excluded-aware path.
These tests prove the line math is correct for a simple AND a per-metre/tax-folded cable line, the
header stays consistent (validator guard still passes), and the unsynced-only gate is server-side.
"""
from decimal import Decimal

import pytest

from app.models.user import User
from app.models.invoice import Invoice, InvoiceItem
from app.services.invoice_validator import validate_invoice

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _active(db, user):
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    db.session.commit()


def _validator_payload(inv):
    """Extraction dict the validator operates on, from the non-excluded lines. unit_price is the
    EX-TAX unit (total_amount / qty) so per-line Check 1 is exercised on a consistent basis."""
    active = [i for i in inv.items if not i.excluded]
    return {
        'items': [
            {'quantity': float(i.quantity),
             'unit_price': float((Decimal(str(i.total_amount)) / Decimal(str(i.quantity)))),
             'total_amount': float(i.total_amount)}
            for i in active
        ],
        'total_ex_tax': float(inv.total_ex_tax),
        'tax_amount': float(inv.supplier_tax_amount),
        'total_inc_tax': float(inv.total_inc_tax),
        'tax_rate': float(inv.supplier_tax_rate),
    }


def _simple_invoice(db, user):
    """One simple line, 5% GST, clean. qty2 x cost10 -> total 20; net 20, tax 1, gross 21."""
    inv = Invoice(user_id=user.id, supplier_name='YESSS Electrical', status='completed',
                  invoice_number='Q-1', supplier_tax_rate=Decimal('5.00'),
                  supplier_tax_amount=Decimal('1.00'), total_cost=Decimal('20.00'),
                  total_ex_tax=Decimal('20.00'), total_inc_tax=Decimal('21.00'),
                  total_selling=Decimal('28.00'), total_profit=Decimal('8.00'),
                  items_count=1, validation_errors=None)
    db.session.add(inv); db.session.flush()
    it = InvoiceItem(invoice_id=inv.id, part_number='WID', description='Widget',
                     quantity=Decimal('2'), cost_per_item=Decimal('10'), total_amount=Decimal('20'),
                     selling_price=Decimal('14'), calculated_selling_price=Decimal('14'),
                     markup_percent=Decimal('40'), profit_per_item=Decimal('4'), price_overridden=False)
    db.session.add(it); db.session.commit()
    return inv, it


def _cable_invoice(db, user):
    """A per-metre cable line where cost_per_item is TAX-INCLUSIVE (non-registered basis), so
    cost_per_item x qty != total_amount — the exact case a naive qty*unit would corrupt.

    Cable: 305 m, ex-tax box net 152.50 (=> ex-tax 0.50/m); cost_per_item 0.5250/m (0.50 + 5% fold);
    sell 0.75/m. Plus a simple 30.00 line. Supplier 5% GST.
    net = 152.50 + 30 = 182.50; tax 9.13; gross 191.63.
    """
    inv = Invoice(user_id=user.id, supplier_name='CEF', status='completed', invoice_number='Q-2',
                  supplier_tax_rate=Decimal('5.00'), supplier_tax_amount=Decimal('9.13'),
                  total_cost=Decimal('182.50'), total_ex_tax=Decimal('182.50'),
                  total_inc_tax=Decimal('191.63'), total_selling=Decimal('273.75'),
                  total_profit=Decimal('91.25'), items_count=2, validation_errors=None)
    db.session.add(inv); db.session.flush()
    cable = InvoiceItem(invoice_id=inv.id, part_number='CAT6-305', description='Cat6 305m box',
                        quantity=Decimal('305'), cost_per_item=Decimal('0.5250'),
                        total_amount=Decimal('152.50'), selling_price=Decimal('0.75'),
                        calculated_selling_price=Decimal('0.75'), markup_percent=Decimal('42.86'),
                        profit_per_item=Decimal('0.225'), price_overridden=False)
    simple = InvoiceItem(invoice_id=inv.id, part_number='MTN150', description='Trunking',
                         quantity=Decimal('1'), cost_per_item=Decimal('30'), total_amount=Decimal('30'),
                         selling_price=Decimal('45'), calculated_selling_price=Decimal('45'),
                         markup_percent=Decimal('50'), profit_per_item=Decimal('15'), price_overridden=False)
    db.session.add_all([cable, simple]); db.session.commit()
    return inv, cable, simple


def test_baseline_invoices_are_clean(app, db, user):
    inv, _ = _simple_invoice(db, user)
    assert validate_invoice(_validator_payload(inv)).is_valid
    inv2, _, _ = _cable_invoice(db, user)
    assert validate_invoice(_validator_payload(inv2)).is_valid


def test_quantity_edit_simple_line(app, db, user):
    _active(db, user)
    inv, it = _simple_invoice(db, user)
    client = app.test_client(); _login(client, user)

    # 2 -> 5 units.
    resp = client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 5}, headers=_HTTPS)
    assert resp.status_code == 200
    u = db.session.get(InvoiceItem, it.id)
    assert u.quantity == Decimal('5.00')
    assert u.total_amount == Decimal('50.00')          # 20 * 5/2 = 50 (ex-tax)
    # Per-unit rates UNCHANGED.
    assert u.cost_per_item == Decimal('10.0000')
    assert u.selling_price == Decimal('14.0000')
    assert u.markup_percent == Decimal('40.00')
    # Header recomputed and internally consistent.
    assert inv.total_cost == Decimal('50.00')
    assert inv.total_ex_tax == Decimal('50.00')
    assert inv.supplier_tax_amount == Decimal('2.50')  # 50 * 5%
    assert inv.total_inc_tax == Decimal('52.50')
    assert inv.total_selling == Decimal('70.00')       # 14 * 5
    assert validate_invoice(_validator_payload(inv)).is_valid
    assert inv.validation_errors is None               # still clean; validator never re-ran


def test_quantity_edit_per_metre_cable_line(app, db, user):
    """The case the naive formula breaks: scaling the EX-TAX total (not cost_per_item x qty)."""
    _active(db, user)
    inv, cable, simple = _cable_invoice(db, user)
    client = app.test_client(); _login(client, user)

    # Return half the box: 305 m -> 152.5 m.
    resp = client.put(f'/invoices/item/{cable.id}/quantity', json={'quantity': 152.5}, headers=_HTTPS)
    assert resp.status_code == 200
    c = db.session.get(InvoiceItem, cable.id)
    assert c.quantity == Decimal('152.50')
    # Proportional EX-TAX total: 152.50 * 152.5/305 = 76.25. (cost_per_item*qty would be 0.5250*152.5
    # = 80.06 — WRONG basis; assert we did NOT do that.)
    assert c.total_amount == Decimal('76.25')
    assert c.total_amount != (c.cost_per_item * c.quantity).quantize(Decimal('0.01'))
    # Per-unit rates UNCHANGED (the per-metre rates survive the qty edit).
    assert c.cost_per_item == Decimal('0.5250')
    assert c.selling_price == Decimal('0.7500')

    # Header: cable 76.25 + simple 30 = 106.25 ex-tax; tax 5.31; gross 111.56.
    assert inv.total_cost == Decimal('106.25')
    assert inv.total_ex_tax == Decimal('106.25')
    assert inv.supplier_tax_amount == Decimal('5.31')  # 106.25 * 5% = 5.3125 -> 5.31
    assert inv.total_inc_tax == Decimal('111.56')
    # selling: 0.75*152.5 + 45 = 114.375->114.38 + 45 = 159.38
    assert inv.total_selling == Decimal('159.38')
    assert validate_invoice(_validator_payload(inv)).is_valid


def test_quantity_edit_rejected_on_synced_invoice(app, db, user):
    """Unsynced-only, enforced SERVER-SIDE (not just the UI)."""
    _active(db, user)
    inv, it = _simple_invoice(db, user)
    from datetime import datetime
    inv.qb_synced_at = datetime.utcnow()
    inv.qb_bill_id = 'BILL-1'
    db.session.commit()
    client = app.test_client(); _login(client, user)

    resp = client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 5}, headers=_HTTPS)
    assert resp.status_code == 409
    assert db.session.get(InvoiceItem, it.id).quantity == Decimal('2.00')  # unchanged


def test_quantity_edit_rejects_non_positive(app, db, user):
    _active(db, user)
    inv, it = _simple_invoice(db, user)
    client = app.test_client(); _login(client, user)
    assert client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 0}, headers=_HTTPS).status_code == 400
    assert client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': -3}, headers=_HTTPS).status_code == 400
    assert client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 'abc'}, headers=_HTTPS).status_code == 400
    assert db.session.get(InvoiceItem, it.id).quantity == Decimal('2.00')  # unchanged


def test_quantity_edit_blocks_other_users_item(app, db, user):
    # Foreign request must be the FIRST in this test: Flask-Login caches the loaded user on `g`
    # within the fixture's app context, so a prior owner request would mask the ownership check.
    _active(db, user)
    inv, it = _simple_invoice(db, user)
    other = User(email='other@example.com', password_hash='x', platform_mode='sync',
                 subscription_plan='pro', subscription_status='active')
    db.session.add(other); db.session.commit()
    oc = app.test_client(); _login(oc, other)
    assert oc.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 5}, headers=_HTTPS).status_code == 403
    assert db.session.get(InvoiceItem, it.id).quantity == Decimal('2.00')  # unchanged


def test_quantity_edit_preserves_price_override(app, db, user):
    """A manual per-unit override is a RATE; a qty edit must keep it (applies to the new qty)."""
    _active(db, user)
    inv, it = _simple_invoice(db, user)
    it.selling_price = Decimal('18'); it.price_overridden = True
    db.session.commit()
    client = app.test_client(); _login(client, user)

    resp = client.put(f'/invoices/item/{it.id}/quantity', json={'quantity': 3}, headers=_HTTPS)
    assert resp.status_code == 200
    u = db.session.get(InvoiceItem, it.id)
    assert u.price_overridden is True                  # override survives
    assert u.selling_price == Decimal('18.0000')       # per-unit rate untouched
    assert inv.total_selling == Decimal('54.00')       # 18 * 3
