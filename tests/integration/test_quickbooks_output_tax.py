"""
Tests for QuickBooks output-GST handling: QuickBooksService.resolve_output_tax
and the sync payloads it drives (Step 3).

Covers the four behaviours from the plan:
  1. Unregistered user -> lines/items push tax-exempt (no output GST).
  2. Registered user -> lines/items carry the GST tax code.
  3. Registered user + no resolvable tax code -> sync BLOCKS (TAX_CODE_UNRESOLVED)
     and nothing is POSTed (fail closed, not the old silent fail-open).
  4. Region/rate selection -> a Jersey 5% GST code is picked over a 20% VAT code
     that is also present (by rate, not list order).

Uses the integration `app` fixture (real testing app + context) so current_app /
config work; make_api_request is replaced with a recording fake so no network or
DB rows are needed.
"""
import types

import pytest

from app.integrations.quickbooks_service import QuickBooksService

# Canned QB TaxCode rows (as the TaxCode query returns them).
GST5 = {'Id': 'G5', 'Name': 'GST 5%'}
VAT20 = {'Id': 'V20', 'Name': 'Standard 20% (VAT on Sales)'}
EXEMPT = {'Id': 'EX', 'Name': 'No GST (0%)'}

LINE_ITEMS = [{'item_id': '1', 'quantity': 2, 'unit_price': 10.0}]
ITEM_DATA = {'name': 'PART1', 'sku': 'PART1', 'cost': 5, 'selling_price': 10,
             'income_account_id': 'IA', 'expense_account_id': 'EA'}


class FakeAPI:
    """Stand-in for make_api_request: routes by endpoint, records POST payloads."""

    def __init__(self, tax_codes, tax_rates=()):
        self.tax_codes = tax_codes
        self.tax_rates = list(tax_rates)
        self.posts = []  # list of (endpoint, data) for every POST

    def __call__(self, qb_connection, endpoint, method='GET', data=None):
        if method == 'POST':
            self.posts.append((endpoint, data))
            obj = dict(data or {})
            obj.setdefault('Id', '999')
            if endpoint.startswith('item'):
                obj.setdefault('Name', (data or {}).get('Name', 'x'))
                return {'Item': obj}
            if endpoint.startswith('invoice'):
                return {'Invoice': obj}
            if endpoint.startswith('estimate'):
                return {'Estimate': obj}
            return {'Obj': obj}
        # GET / query
        if 'FROM TaxCode' in endpoint:
            return {'QueryResponse': {'TaxCode': list(self.tax_codes)}}
        if 'FROM TaxRate' in endpoint:
            return {'QueryResponse': {'TaxRate': list(self.tax_rates)}}
        if 'FROM Item' in endpoint:
            return {'QueryResponse': {}}  # no existing item -> create path
        return {}

    def item_posts(self):
        return [d for (ep, d) in self.posts if ep.startswith('item')]

    def invoice_posts(self):
        return [d for (ep, d) in self.posts if ep.startswith('invoice')]


def make_service(tax_codes, *, tax_registered=True, tax_type='GST', tax_rate=5,
                 country='Jersey', tax_rates=()):
    user = types.SimpleNamespace(
        id=1,
        tax_registered=tax_registered,
        tax_type=tax_type,
        tax_rate=tax_rate,
        country=country,
        business_address_country=country,
    )
    svc = QuickBooksService(user)
    api = FakeAPI(tax_codes, tax_rates=tax_rates)
    svc.make_api_request = api
    return svc, api


CONN = types.SimpleNamespace(default_income_account_id='IA',
                             default_expense_account_id='EA')


# ── 1. Unregistered: no output GST ───────────────────────────────────────────
def test_unregistered_item_uses_exempt_code_not_gst(app):
    svc, api = make_service([GST5, EXEMPT], tax_registered=False, tax_type='', tax_rate=0)
    svc.create_or_update_item(CONN, dict(ITEM_DATA))
    payload = api.item_posts()[0]
    assert payload['SalesTaxCodeRef'] == {'value': 'EX'}   # exempt, NOT the 5% GST code
    assert payload['SalesTaxCodeRef'] != {'value': 'G5'}


def test_unregistered_item_no_exempt_code_is_taxable_false(app):
    svc, api = make_service([GST5], tax_registered=False, tax_type='', tax_rate=0)
    svc.create_or_update_item(CONN, dict(ITEM_DATA))
    payload = api.item_posts()[0]
    assert payload['Taxable'] is False
    assert 'SalesTaxCodeRef' not in payload


def test_unregistered_invoice_line_has_no_gst_code(app):
    svc, api = make_service([GST5], tax_registered=False, tax_type='', tax_rate=0)
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    line = api.invoice_posts()[0]['Line'][0]
    assert 'TaxCodeRef' not in line['SalesItemLineDetail']


# ── 2. Registered: lines/items carry the GST code ────────────────────────────
def test_registered_invoice_line_carries_gst_code(app):
    svc, api = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    line = api.invoice_posts()[0]['Line'][0]
    assert line['SalesItemLineDetail']['TaxCodeRef'] == {'value': 'G5'}


def test_registered_item_carries_gst_code(app):
    svc, api = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    svc.create_or_update_item(CONN, dict(ITEM_DATA))
    payload = api.item_posts()[0]
    assert payload['Taxable'] is True
    assert payload['SalesTaxCodeRef'] == {'value': 'G5'}


# ── 3. Registered + no resolvable code: fail closed, no POST ─────────────────
def test_registered_no_taxcode_blocks_invoice_with_no_post(app):
    svc, api = make_service([], tax_registered=True, tax_type='GST', tax_rate=5)
    result = svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert api.posts == []   # nothing was POSTed


def test_registered_no_taxcode_blocks_product_sync_with_no_post(app):
    svc, api = make_service([], tax_registered=True, tax_type='GST', tax_rate=5)
    invoice = types.SimpleNamespace(id=1)
    result = svc.sync_invoice_items_as_products(CONN, invoice)
    assert result['success'] is False
    assert result['code'] == 'TAX_CODE_UNRESOLVED'
    assert api.posts == []


# ── 4. Region/rate selection: Jersey 5% wins over a 20% VAT code present ──────
def test_jersey_gst_picked_over_vat_by_rate(app):
    # VAT listed FIRST to prove it is rate-matched, not first-wins.
    svc, _ = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert code['value'] == 'G5'


def test_unset_config_with_multiple_codes_is_unresolved(app):
    # No tax_rate/tax_type set AND multiple sales codes -> genuine ambiguity -> fail
    # closed. We deliberately do NOT guess from address country (Step 3c req 4): an
    # address of 'United Kingdom' for a Jersey GST business would wrongly pick 20%.
    svc, _ = make_service([VAT20, GST5], tax_registered=True, tax_type='', tax_rate=0,
                          country=None)
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'unresolved'
    assert code is None


# ── 5. Real-world shapes + Step 2c match-or-fail ─────────────────────────────────
# Live company shape: one sales code named just "GST" (id 2), rate in its TaxRateRef
# detail (not the name).
GST_REAL = {'Id': '2', 'Name': 'GST',
            'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '5'}}]}}


def test_single_gst_code_with_configured_rate_is_taxable(app):
    # Proton.je shape once configured: sole "GST" code (5% in detail), user tax_rate=5 ->
    # match-or-fail succeeds and attaches it.
    svc, _ = make_service([GST_REAL], tax_registered=True, tax_type='GST', tax_rate=5,
                          country=None, tax_rates=[{'Id': '5', 'RateValue': 5}])
    assert svc.resolve_output_tax(CONN) == ({'value': '2', 'name': 'GST'}, 'taxable')


def test_registered_rate_unset_is_unresolved(app):
    # 2c: a registered user with NO configured output rate cannot reconcile doc vs sync
    # — the 3c single-code fallback is gone; match-or-fail needs a configured rate.
    svc, _ = make_service([GST_REAL], tax_registered=True, tax_type='', tax_rate=0,
                          country=None, tax_rates=[{'Id': '5', 'RateValue': 5}])
    assert svc.resolve_output_tax(CONN) == (None, 'unresolved')


def test_registered_rate_mismatch_fails_closed(app):
    # 2c: configured 20% but the only code is 5% -> no match -> fail closed (never
    # silently attach a rate the user didn't configure / the document didn't show).
    svc, _ = make_service([GST_REAL], tax_registered=True, tax_type='', tax_rate=20,
                          country=None, tax_rates=[{'Id': '5', 'RateValue': 5}])
    assert svc.resolve_output_tax(CONN) == (None, 'unresolved')


def test_registered_matches_by_real_rate_from_detail(app):
    # Two codes named just "GST"/"VAT" (no % in either name) — rate lives only in the
    # TaxRateRef detail. With tax_rate=5 the resolver must pick the one whose REAL
    # rate is 5, proving it no longer trusts the name for the rate.
    gst = {'Id': '2', 'Name': 'GST',
           'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '5'}}]}}
    vat = {'Id': '3', 'Name': 'VAT',
           'SalesTaxRateList': {'TaxRateDetail': [{'TaxRateRef': {'value': '9'}}]}}
    svc, _ = make_service([vat, gst], tax_registered=True, tax_type='', tax_rate=5,
                          country=None,
                          tax_rates=[{'Id': '5', 'RateValue': 5}, {'Id': '9', 'RateValue': 20}])
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert code['value'] == '2'
