"""Sync gate must be ALL-OR-NOTHING: a validation-blocked invoice writes NOTHING to
QuickBooks or Xero — not the bill/estimate, and (the bug this fixes) not the product
catalog either.

Every test mocks the HTTP layer (QuickBooksService.make_api_request / XeroService._make_request)
and asserts ZERO write calls on a blocked invoice across route, service, and primitive paths for
both providers + the estimate route; and that a clean invoice still issues its writes.
"""
import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.integrations.quickbooks_service import QuickBooksService
from app.integrations.xero_service import XeroService


# ── invoice data (lines carry part numbers so the product sync would write if unguarded) ──
def _items():
    return [
        {'part_number': 'WMSS82', 'description': 'Back box', 'quantity': 2, 'unit_price': 10,
         'total_amount': 20, 'cost_per_item': 10, 'selling_price': 15, 'original_unit_price': 10,
         'markup_percent': 50, 'profit_per_item': 5},
        {'part_number': 'MTN150', 'description': 'Trunking', 'quantity': 1, 'unit_price': 30,
         'total_amount': 30, 'cost_per_item': 30, 'selling_price': 45, 'original_unit_price': 30,
         'markup_percent': 50, 'profit_per_item': 15},
    ]


def _clean():
    # lines sum to net 50; 50 + 10 (20%) = 60 → validator passes, reconciler no-op.
    return {'supplier': 'CEF', 'invoice_number': 'INV-CLEAN-GATE', 'items': _items(),
            'total_ex_tax': 50, 'tax_amount': 10, 'total_inc_tax': 60, 'tax_rate': 20}


def _blocked():
    # lines sum 50 but stated net 90 (and 90+18≠ a matching gross via lines) → blocked, no reconcile.
    d = _clean()
    d['invoice_number'] = 'INV-BLOCK-GATE'
    d['total_ex_tax'] = 90
    d['tax_amount'] = 18
    d['total_inc_tax'] = 108
    return d


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    monkeypatch.setattr(upload_module, 'current_user', user)


@pytest.fixture
def blocked_invoice(app, user):
    inv = save_invoice_to_db(_blocked(), 'b.pdf', user.id)
    assert inv.validation_errors is not None  # precondition: it really is blocked
    return inv


@pytest.fixture
def clean_invoice(app, user):
    inv = save_invoice_to_db(_clean(), 'c.pdf', user.id)
    assert inv.validation_errors is None
    return inv


@pytest.fixture
def blocked_quote(app, user):
    return save_invoice_to_db(_blocked(), 'q.pdf', user.id, document_type='quote')


@pytest.fixture
def qb_conn(db, user):
    from app.models.quickbooks import QuickBooksConnection
    c = QuickBooksConnection(user_id=user.id, realm_id='r', access_token='a', refresh_token='r',
                             is_active=True, default_income_account_id='1',
                             default_expense_account_id='2')
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def xero_conn(db, user):
    from datetime import datetime
    from app.models.xero import XeroConnection
    c = XeroConnection(user_id=user.id, tenant_id='t', access_token='a', refresh_token='r',
                       token_expires_at=datetime.utcnow(), is_active=True,
                       default_expense_account_code='200', default_sales_account_code='201')
    db.session.add(c)
    db.session.commit()
    return c


def _client(app, user, db):
    # Clear the trial/subscription wall (a pre-existing before_request guard) so the
    # request reaches the sync gate under test, not the billing redirect.
    user.subscription_plan = 'full-starter'
    user.subscription_status = 'active'
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return c


# ════════════════════════ QuickBooks ════════════════════════
def test_qb_service_products_blocked_zero_writes(app, user, blocked_invoice, qb_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(QuickBooksService, 'make_api_request', lambda self, *a, **k: calls.append(a) or {})
    res = QuickBooksService(user).sync_invoice_items_as_products(qb_conn, blocked_invoice)
    assert res.get('code') == 'VALIDATION_BLOCKED'
    assert calls == []  # not even the tax-code query fired


def test_qb_primitive_create_item_blocked_zero_writes(app, user, blocked_invoice, qb_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(QuickBooksService, 'make_api_request', lambda self, *a, **k: calls.append(a) or {})
    res = QuickBooksService(user).create_or_update_item(
        qb_conn, {'name': 'WMSS82', 'sku': 'WMSS82', 'selling_price': 4.20}, invoice=blocked_invoice)
    assert res.get('code') == 'VALIDATION_BLOCKED'
    assert calls == []


def test_qb_bill_blocked_zero_writes(app, user, blocked_invoice, qb_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(QuickBooksService, 'make_api_request', lambda self, *a, **k: calls.append(a) or {})
    res = QuickBooksService(user).sync_invoice_to_quickbooks(qb_conn, blocked_invoice)
    assert res.get('code') == 'VALIDATION_BLOCKED'
    assert calls == []


def test_qb_service_products_clean_writes(app, user, clean_invoice, qb_conn, monkeypatch):
    calls = []

    def fake(self, conn, endpoint, method='GET', data=None):
        calls.append((endpoint, method))
        return {'Item': {'Id': '1', 'Name': 'X'}} if (endpoint == 'item' and method == 'POST') else {}
    monkeypatch.setattr(QuickBooksService, 'make_api_request', fake)
    monkeypatch.setattr(QuickBooksService, 'resolve_output_tax', lambda self, conn: ({'value': '2'}, 'ok'))
    res = QuickBooksService(user).sync_invoice_items_as_products(qb_conn, clean_invoice)
    assert res['synced'] > 0
    assert any(ep == 'item' and m == 'POST' for ep, m in calls)  # catalog write happened


def test_route_qb_products_blocked_zero_writes(app, user, db, blocked_invoice, qb_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(QuickBooksService, 'make_api_request', lambda self, *a, **k: calls.append(a) or {})
    r = _client(app, user, db).post(f'/integrations/quickbooks/sync-products/{blocked_invoice.id}',
                                headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 400
    assert r.json['validation_errors']
    assert calls == []


def test_route_qb_estimate_blocked_zero_writes(app, user, db, blocked_quote, qb_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(QuickBooksService, 'make_api_request', lambda self, *a, **k: calls.append(a) or {})
    r = _client(app, user, db).post(f'/integrations/quickbooks/create-estimate/{blocked_quote.id}',
                                json={'customer_id': '1'}, headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 400
    assert calls == []


# ════════════════════════ Xero (no tax fail-closed today — most exposed) ════════════════════════
def test_xero_service_products_blocked_zero_writes(app, user, blocked_invoice, xero_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(XeroService, '_make_request', lambda self, *a, **k: calls.append(a) or {})
    res = XeroService(user).sync_products_to_items(xero_conn, blocked_invoice)
    assert res.get('code') == 'VALIDATION_BLOCKED'
    assert calls == []  # not even GET /Items fired


def test_xero_primitive_find_or_create_blocked_zero_writes(app, user, blocked_invoice, xero_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(XeroService, '_make_request', lambda self, *a, **k: calls.append(a) or {})
    res = XeroService(user).find_or_create_item(
        xero_conn, code='WMSS82', name='x', description='', purchase_price=1.0, sale_price=4.20,
        purchase_account_code='200', sales_account_code='201', invoice=blocked_invoice)
    assert res is None  # no item, no write
    assert calls == []


def test_xero_service_products_clean_writes(app, user, clean_invoice, xero_conn, monkeypatch):
    calls = []

    def fake(self, method, path, connection, data=None):
        calls.append((method, path))
        if method == 'GET' and path == '/Items':
            return {'Items': []}
        if method == 'POST' and path == '/Items':
            return {'Items': [{'ItemID': '1', 'Code': 'X'}]}
        return {}
    monkeypatch.setattr(XeroService, '_make_request', fake)
    res = XeroService(user).sync_products_to_items(xero_conn, clean_invoice)
    assert res['synced'] > 0
    assert ('POST', '/Items') in calls  # catalog write happened


def test_route_xero_products_blocked_zero_writes(app, user, db, blocked_invoice, xero_conn, monkeypatch):
    calls = []
    monkeypatch.setattr(XeroService, '_make_request', lambda self, *a, **k: calls.append(a) or {})
    r = _client(app, user, db).post(f'/integrations/xero/sync-products/{blocked_invoice.id}',
                                headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 400
    assert calls == []
