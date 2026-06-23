"""Step 2c — the printed customer-document tax is anchored to the same source as the
QB/Xero resolver: effective_output_rate(user) = (tax_registered ? tax_rate : 0).

Covers: the helper; the document snapshots that rate at create; unregistered → no tax
line; the registered-but-rate-unset guard; and snapshot immutability (a later config
change does NOT rewrite an existing document's rate).
"""
import types
from decimal import Decimal

import pytest

from app.extensions import db as _db
from app.models.customer import Customer
from app.models.customer_invoice import CustomerInvoice
from app.utils.tax import effective_output_rate, output_rate_unconfigured

_HTTPS = {'X-Forwarded-Proto': 'https'}


# ── helper: the single source of truth ───────────────────────────────────────
def test_effective_output_rate_unregistered_is_zero():
    u = types.SimpleNamespace(tax_registered=False, tax_rate=Decimal('5'))  # stale rate ignored
    assert effective_output_rate(u) == Decimal('0')


def test_effective_output_rate_registered_uses_configured_rate():
    u = types.SimpleNamespace(tax_registered=True, tax_rate=Decimal('5'))
    assert effective_output_rate(u) == Decimal('5')


def test_output_rate_unconfigured_predicate():
    assert output_rate_unconfigured(types.SimpleNamespace(tax_registered=True, tax_rate=0)) is True
    assert output_rate_unconfigured(types.SimpleNamespace(tax_registered=True, tax_rate=Decimal('5'))) is False
    assert output_rate_unconfigured(types.SimpleNamespace(tax_registered=False, tax_rate=0)) is False


# ── document create via the real route ───────────────────────────────────────
def _full_user(db, user, *, registered, rate):
    user.platform_mode = 'full'
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    user.tax_registered = registered
    user.tax_rate = Decimal(str(rate))
    db.session.commit()
    cust = Customer(user_id=user.id, name='Acme Ltd')
    db.session.add(cust)
    db.session.commit()
    return cust


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _manual_payload(customer_id):
    return {
        'customer_id': customer_id,
        'issue_date': '2026-06-20', 'due_date': '2026-07-20',
        'tax_rate': 99,  # client value — must be ignored
        'subtotal': 999, 'tax_amount': 999, 'total': 999,  # client totals — must be ignored
        'lines': [{'description': 'Work', 'quantity': 2, 'unit_price': '10.00', 'line_total': 999}],
    }


def test_registered_document_snapshots_effective_rate(app, db, user):
    cust = _full_user(db, user, registered=True, rate=5)
    client = app.test_client()
    _login(client, user)
    resp = client.post('/customer-invoices/create-manual', json=_manual_payload(cust.id), headers=_HTTPS)
    assert resp.status_code == 200 and resp.get_json()['success']
    inv = CustomerInvoice.query.filter_by(user_id=user.id).order_by(CustomerInvoice.id.desc()).first()
    assert inv.tax_rate == effective_output_rate(user) == Decimal('5')   # config snapshot, not client 99
    assert inv.subtotal == Decimal('20.00')                              # server-recomputed from line
    assert inv.tax_amount == Decimal('1.00')                             # money(20 × 5%)
    assert inv.total == inv.subtotal + inv.tax_amount


def test_unregistered_document_has_no_tax_line(app, db, user):
    cust = _full_user(db, user, registered=False, rate=5)  # stale rate present but unregistered
    client = app.test_client()
    _login(client, user)
    resp = client.post('/customer-invoices/create-manual', json=_manual_payload(cust.id), headers=_HTTPS)
    assert resp.status_code == 200
    inv = CustomerInvoice.query.filter_by(user_id=user.id).order_by(CustomerInvoice.id.desc()).first()
    assert inv.tax_rate == Decimal('0')
    assert inv.tax_amount == Decimal('0.00')          # no tax line (matches exempt sync)


def test_registered_but_rate_unset_guard_blocks_create(app, db, user):
    cust = _full_user(db, user, registered=True, rate=0)   # registered, no rate -> config error
    client = app.test_client()
    _login(client, user)
    before = CustomerInvoice.query.filter_by(user_id=user.id).count()
    resp = client.post('/customer-invoices/create-manual', json=_manual_payload(cust.id), headers=_HTTPS)
    assert resp.status_code == 400
    assert 'output tax rate' in resp.get_json()['error'].lower()
    assert CustomerInvoice.query.filter_by(user_id=user.id).count() == before  # nothing created


def test_rate_snapshot_is_immutable_after_config_change(app, db, user):
    cust = _full_user(db, user, registered=True, rate=5)
    client = app.test_client()
    _login(client, user)
    client.post('/customer-invoices/create-manual', json=_manual_payload(cust.id), headers=_HTTPS)
    inv = CustomerInvoice.query.filter_by(user_id=user.id).order_by(CustomerInvoice.id.desc()).first()
    inv_id = inv.id
    assert inv.tax_rate == Decimal('5')

    # User later changes their configured rate — the issued document must NOT change.
    user.tax_rate = Decimal('20')
    db.session.commit()
    _db.session.expire_all()
    assert CustomerInvoice.query.get(inv_id).tax_rate == Decimal('5')   # immutable snapshot
