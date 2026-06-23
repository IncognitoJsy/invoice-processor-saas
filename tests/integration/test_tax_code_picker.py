"""
Tests for the output-tax-code PICKER (commit 2/7) — the read-only data source.

Two layers:
  1. Service listing: QuickBooksService/XeroService.list_sales_tax_codes return the active,
     sales-applicable codes with their REAL rate, flag exempt/zero codes, and exclude
     purchase-only ones. These reuse the SAME GET-only reads as the resolver — no writes.
  2. The GET /settings/tax-codes endpoint: returns the connected provider's codes as JSON,
     reflects the user's current pick, and reports "nothing connected" cleanly.

Uses the integration `app` fixture; make_api_request / get_tax_rates are replaced with
recording fakes so no network or live tokens are needed.
"""
import types

import pytest

from app.integrations.quickbooks_service import QuickBooksService
from app.integrations.xero_service import XeroService
from app.models.quickbooks import QuickBooksConnection


# ── QB TaxCode/TaxRate shapes ────────────────────────────────────────────────
GST_REAL = {'Id': '2', 'Name': 'GST',
            'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '5'}}]}}
VAT20 = {'Id': '3', 'Name': 'VAT',
         'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '9'}}]}}
EXEMPT = {'Id': 'EX', 'Name': 'No GST (0%)'}
PURCHASE_ONLY = {'Id': 'P1', 'Name': 'GST on Purchases',
                 'PurchaseTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '5'}}]}}
QB_RATES = [{'Id': '5', 'RateValue': 5}, {'Id': '9', 'RateValue': 20}]

CONN = types.SimpleNamespace(default_income_account_id='IA', default_expense_account_id='EA')


class FakeQBAPI:
    def __init__(self, tax_codes, tax_rates):
        self.tax_codes, self.tax_rates = list(tax_codes), list(tax_rates)

    def __call__(self, qb_connection, endpoint, method='GET', data=None):
        assert method == 'GET', "picker listing must never POST"
        if 'FROM TaxCode' in endpoint:
            return {'QueryResponse': {'TaxCode': list(self.tax_codes)}}
        if 'FROM TaxRate' in endpoint:
            return {'QueryResponse': {'TaxRate': list(self.tax_rates)}}
        return {}


def _qb_service(tax_codes, tax_rates=QB_RATES):
    svc = QuickBooksService(types.SimpleNamespace(id=1, tax_registered=True, tax_rate=5))
    svc.make_api_request = FakeQBAPI(tax_codes, tax_rates)
    return svc


def test_qb_list_resolves_real_rates_and_flags_exempt(app):
    codes = _qb_service([GST_REAL, VAT20, EXEMPT]).list_sales_tax_codes(CONN)
    by_ref = {c['ref']: c for c in codes}
    assert by_ref['2']['rate'] == 5 and by_ref['2']['exempt'] is False
    assert by_ref['3']['rate'] == 20
    assert by_ref['EX']['exempt'] is True and by_ref['EX']['rate'] == 0


def test_qb_list_excludes_purchase_only_codes(app):
    refs = {c['ref'] for c in _qb_service([GST_REAL, PURCHASE_ONLY]).list_sales_tax_codes(CONN)}
    assert refs == {'2'}  # purchase-only code is not offered for a sales pick


# ── Xero TaxRate shapes ──────────────────────────────────────────────────────
XERO_GST = {'TaxType': 'OUTPUT', 'Name': 'GST on Income', 'EffectiveRate': 5,
            'Status': 'ACTIVE', 'CanApplyToRevenue': True}
XERO_EXEMPT = {'TaxType': 'NONE', 'Name': 'No Tax', 'EffectiveRate': 0,
               'Status': 'ACTIVE', 'CanApplyToRevenue': True}
XERO_INPUT = {'TaxType': 'INPUT', 'Name': 'GST on Expenses', 'EffectiveRate': 5,
              'Status': 'ACTIVE', 'CanApplyToRevenue': False}


def _xero_service(rates):
    svc = XeroService(types.SimpleNamespace(id=1, tax_registered=True, tax_rate=5))
    svc.get_tax_rates = lambda connection: list(rates)
    return svc


def test_xero_list_resolves_rates_excludes_input(app):
    codes = _xero_service([XERO_GST, XERO_EXEMPT, XERO_INPUT]).list_sales_tax_codes(object())
    by_ref = {c['ref']: c for c in codes}
    assert 'INPUT' not in by_ref               # purchase/input rate not offered for sales
    assert by_ref['OUTPUT']['rate'] == 5 and by_ref['OUTPUT']['exempt'] is False
    assert by_ref['NONE']['exempt'] is True


# ── GET /settings/tax-codes endpoint ─────────────────────────────────────────
_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _active_plan(db, user):
    """The endpoint sits behind the subscription gate; give the user an active plan."""
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    db.session.commit()


def test_endpoint_no_connection_reports_nothing_connected(app, db, user):
    _active_plan(db, user)
    client = app.test_client()
    _login(client, user)
    data = client.get('/settings/tax-codes', headers=_HTTPS).get_json()
    assert data['success'] is True and data['provider'] is None and data['codes'] == []
    assert 'Connect QuickBooks or Xero' in data['message']


def test_endpoint_lists_qb_codes_and_current_pick(app, db, user, monkeypatch):
    db.session.add(QuickBooksConnection(
        user_id=user.id, realm_id='R1', access_token='tok', refresh_token='r', is_active=True))
    # Already picked GST (id 2, 5%) — endpoint should echo it as `current`.
    user.output_tax_code_ref = '2'
    user.output_tax_code_name = 'GST'
    user.output_tax_provider = 'quickbooks'
    user.tax_registered = True
    user.tax_rate = 5
    _active_plan(db, user)

    monkeypatch.setattr(
        'app.integrations.quickbooks_service.QuickBooksService.list_sales_tax_codes',
        lambda self, conn: [{'ref': '2', 'name': 'GST', 'rate': __import__('decimal').Decimal('5'),
                             'exempt': False}])

    client = app.test_client()
    _login(client, user)
    data = client.get('/settings/tax-codes', headers=_HTTPS).get_json()
    assert data['provider'] == 'quickbooks'
    assert data['codes'] == [{'ref': '2', 'name': 'GST', 'rate': 5.0, 'exempt': False}]
    assert data['current'] == {'ref': '2', 'name': 'GST', 'rate': 5.0}


def test_endpoint_listing_error_returns_502(app, db, user, monkeypatch):
    db.session.add(QuickBooksConnection(
        user_id=user.id, realm_id='R1', access_token='tok', refresh_token='r', is_active=True))
    _active_plan(db, user)

    def _boom(self, conn):
        raise RuntimeError("QBO unreachable")
    monkeypatch.setattr(
        'app.integrations.quickbooks_service.QuickBooksService.list_sales_tax_codes', _boom)

    client = app.test_client()
    _login(client, user)
    resp = client.get('/settings/tax-codes', headers=_HTTPS)
    assert resp.status_code == 502
    assert resp.get_json()['success'] is False
