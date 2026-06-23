"""
Tests for the per-line manual price override (features 2+3, one shared price_overridden state)
and the hardened update_item_price endpoint: money() rounding, markup recompute, cap bypass,
explicit ?reset, ownership, and the extended to_dict.
"""
from decimal import Decimal

import pytest

from app.models.user import User
from app.models.invoice import Invoice, InvoiceItem

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _active(db, user):
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    db.session.commit()


def _item(db, user, **kw):
    inv = Invoice(user_id=user.id, supplier_name='YESSS Electrical', status='completed',
                  invoice_number='T-1', total_cost=Decimal('20'))
    db.session.add(inv); db.session.flush()
    defaults = dict(invoice_id=inv.id, part_number='WID', description='Widget',
                    quantity=Decimal('2'), cost_per_item=Decimal('10'),
                    original_unit_price=Decimal('15'), discount_percent=Decimal('20'),
                    total_amount=Decimal('20'), selling_price=Decimal('14'),
                    calculated_selling_price=Decimal('14'), markup_percent=Decimal('40'),
                    profit_per_item=Decimal('4'), price_overridden=False)
    defaults.update(kw)
    it = InvoiceItem(**defaults)
    db.session.add(it); db.session.commit()
    return inv, it


def test_override_sets_manual_state_and_recomputes(app, db, user):
    _active(db, user)
    inv, it = _item(db, user)
    client = app.test_client(); _login(client, user)
    # 18.00/u is ABOVE the retail/list 15.00 — a deliberate manual price must stand (cap bypassed).
    resp = client.put(f'/invoices/item/{it.id}/price', json={'selling_price': 18}, headers=_HTTPS)
    assert resp.status_code == 200
    u = db.session.get(InvoiceItem, it.id)
    # Override (18) is ABOVE the line's retail/list price (15) and must STAND (cap is parse-time
    # only; the override path never caps) AND flag price_overridden so the MANUAL badge renders.
    assert u.original_unit_price == Decimal('15')
    assert u.selling_price == Decimal('18.00')          # > retail 15 — NOT capped
    assert u.selling_price > u.original_unit_price       # explicitly above retail
    assert u.price_overridden is True                    # drives the ⚑ MANUAL badge
    assert u.markup_percent == Decimal('80.00')         # (18-10)/10*100
    assert u.profit_per_item == Decimal('8.00')
    assert u.updated_at is not None
    body = resp.get_json()
    assert body['invoice_totals']['total_selling'] == 36.0   # 18 * qty 2
    assert body['invoice_totals']['total_profit'] == 16.0


def test_override_rounds(app, db, user):
    _active(db, user)
    inv, it = _item(db, user)
    client = app.test_client(); _login(client, user)
    resp = client.put(f'/invoices/item/{it.id}/price', json={'selling_price': '18.126'}, headers=_HTTPS)
    assert resp.status_code == 200
    assert db.session.get(InvoiceItem, it.id).selling_price == Decimal('18.13')  # money() ROUND_HALF_UP


def test_reset_clears_override_back_to_calculated(app, db, user):
    _active(db, user)
    inv, it = _item(db, user, selling_price=Decimal('18'), price_overridden=True,
                    markup_percent=Decimal('80'), profit_per_item=Decimal('8'))
    client = app.test_client(); _login(client, user)
    resp = client.put(f'/invoices/item/{it.id}/price?reset=true', headers=_HTTPS)
    assert resp.status_code == 200
    u = db.session.get(InvoiceItem, it.id)
    assert u.price_overridden is False
    assert u.selling_price == Decimal('14.00')          # back to calculated_selling_price
    assert u.markup_percent == Decimal('40.00')         # (14-10)/10*100


def test_override_rejects_non_positive(app, db, user):
    _active(db, user)
    inv, it = _item(db, user)
    client = app.test_client(); _login(client, user)
    assert client.put(f'/invoices/item/{it.id}/price', json={'selling_price': 0}, headers=_HTTPS).status_code == 400
    assert client.put(f'/invoices/item/{it.id}/price', json={'selling_price': 'abc'}, headers=_HTTPS).status_code == 400
    assert db.session.get(InvoiceItem, it.id).price_overridden is False  # unchanged


def test_override_blocks_other_users_item(app, db, user):
    _active(db, user)
    inv, it = _item(db, user)
    other = User(email='other@example.com', password_hash='x', platform_mode='sync',
                 subscription_plan='pro', subscription_status='active')
    db.session.add(other); db.session.commit()
    client = app.test_client(); _login(client, other)
    assert client.put(f'/invoices/item/{it.id}/price', json={'selling_price': 18}, headers=_HTTPS).status_code == 403


def test_to_dict_exposes_new_fields(app, db, user):
    _active(db, user)
    inv, it = _item(db, user, price_overridden=True)
    d = db.session.get(InvoiceItem, it.id).to_dict()
    for k in ('original_unit_price', 'discount_percent', 'markup_percent',
              'price_overridden', 'created_at', 'updated_at'):
        assert k in d, k
    assert d['price_overridden'] is True
    assert d['original_unit_price'] == 15.0
