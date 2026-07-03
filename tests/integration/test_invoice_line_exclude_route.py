"""Phase 4: the exclude/restore route (PUT /invoices/item/<id>/exclude).

Soft-remove and restore a line before sync, recomputing the header via the shared path, gated
unsynced-only server-side. (The recompute maths + sync filtering are pinned in
test_invoice_line_excluded.py / _sync.py; here we pin the ROUTE.)
"""
from decimal import Decimal
from datetime import datetime

import pytest

from app.models.user import User
from app.models.invoice import Invoice, InvoiceItem

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _active(db, user):
    user.subscription_plan = 'pro'; user.subscription_status = 'active'
    db.session.commit()


def _two_line(db, user):
    """A(20) + B(30): net 50, 5% GST → tax 2.50, gross 52.50; selling 28 + 45 = 73."""
    inv = Invoice(user_id=user.id, supplier_name='CEF', status='completed', invoice_number='X-1',
                  supplier_tax_rate=Decimal('5.00'), supplier_tax_amount=Decimal('2.50'),
                  total_cost=Decimal('50.00'), total_ex_tax=Decimal('50.00'),
                  total_inc_tax=Decimal('52.50'), total_selling=Decimal('73.00'),
                  total_profit=Decimal('23.00'), items_count=2, validation_errors=None)
    db.session.add(inv); db.session.flush()
    a = InvoiceItem(invoice_id=inv.id, part_number='A', quantity=Decimal('2'), cost_per_item=Decimal('10'),
                    total_amount=Decimal('20'), selling_price=Decimal('14'), profit_per_item=Decimal('4'))
    b = InvoiceItem(invoice_id=inv.id, part_number='B', quantity=Decimal('1'), cost_per_item=Decimal('30'),
                    total_amount=Decimal('30'), selling_price=Decimal('45'), profit_per_item=Decimal('15'))
    db.session.add_all([a, b]); db.session.commit()
    return inv, a, b


def test_exclude_then_restore_recomputes_header(app, db, user):
    _active(db, user)
    inv, a, b = _two_line(db, user)
    client = app.test_client(); _login(client, user)

    # Exclude A (£20 line).
    r = client.put(f'/invoices/item/{a.id}/exclude', headers=_HTTPS)
    assert r.status_code == 200
    assert r.get_json()['item']['excluded'] is True
    assert db.session.get(InvoiceItem, a.id).excluded is True
    assert inv.total_cost == Decimal('30.00')          # only B
    assert inv.total_ex_tax == Decimal('30.00')
    assert inv.supplier_tax_amount == Decimal('1.50')  # 30 * 5%
    assert inv.total_inc_tax == Decimal('31.50')
    assert inv.total_selling == Decimal('45.00')
    assert inv.validation_errors is None               # never re-validates

    # Restore A → header back to the full totals.
    r = client.put(f'/invoices/item/{a.id}/exclude?restore=true', headers=_HTTPS)
    assert r.status_code == 200
    assert r.get_json()['item']['excluded'] is False
    assert db.session.get(InvoiceItem, a.id).excluded is False
    assert inv.total_cost == Decimal('50.00')
    assert inv.total_selling == Decimal('73.00')


def test_exclude_rejected_on_synced_invoice(app, db, user):
    _active(db, user)
    inv, a, b = _two_line(db, user)
    inv.qb_synced_at = datetime.utcnow(); inv.qb_bill_id = 'BILL-1'
    db.session.commit()
    client = app.test_client(); _login(client, user)

    r = client.put(f'/invoices/item/{a.id}/exclude', headers=_HTTPS)
    assert r.status_code == 409
    assert db.session.get(InvoiceItem, a.id).excluded is False  # unchanged


def test_exclude_blocks_other_users_item(app, db, user):
    # Foreign request first (Flask-Login caches the loaded user on `g` within the app context).
    _active(db, user)
    inv, a, b = _two_line(db, user)
    other = User(email='other@example.com', password_hash='x', platform_mode='sync',
                 subscription_plan='pro', subscription_status='active')
    db.session.add(other); db.session.commit()
    oc = app.test_client(); _login(oc, other)
    assert oc.put(f'/invoices/item/{a.id}/exclude', headers=_HTTPS).status_code == 403
    assert db.session.get(InvoiceItem, a.id).excluded is False
