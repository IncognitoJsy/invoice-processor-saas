"""
Tests for QuickBooks output-GST handling: QuickBooksService.resolve_output_tax
and the sync payloads it drives.

Behaviour (post tax-code PICKER, commit 4/7):
  1. Unregistered user -> lines/items push tax-exempt (no output GST).
  2. Registered user with a PICKED QuickBooks tax code -> lines/items carry that code,
     attached DIRECTLY by its stored ref (no per-sync TaxRate read, no rate match).
  3. Registered user with NO pick -> sync BLOCKS (TAX_CODE_UNRESOLVED) and nothing is
     POSTed (fail closed).
  4. The pick is authoritative: the code attached is exactly the picked ref regardless of
     what other codes exist in the company file, and a pick made for a different provider
     (e.g. Xero) does NOT satisfy the QuickBooks resolver.

Uses the integration `app` fixture so current_app / config work; make_api_request is
replaced with a recording fake so no network or DB rows are needed.
"""
import types

import pytest

from app.integrations.quickbooks_service import QuickBooksService

# Canned QB TaxCode rows (as the TaxCode query returns them) — used by the exempt path.
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
                 country='Jersey', tax_rates=(), picked=None, picked_provider='quickbooks'):
    """`picked` is (ref, name) for a stored QuickBooks tax-code pick, or None."""
    user = types.SimpleNamespace(
        id=1,
        tax_registered=tax_registered,
        tax_type=tax_type,
        tax_rate=tax_rate,
        country=country,
        business_address_country=country,
        output_tax_code_ref=(picked[0] if picked else None),
        output_tax_code_name=(picked[1] if picked else None),
        output_tax_provider=(picked_provider if picked else None),
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


# ── 2. Registered + picked code: lines/items carry the PICKED ref ────────────
def test_registered_invoice_line_carries_picked_code(app):
    svc, api = make_service([VAT20, GST5], tax_registered=True, picked=('G5', 'GST 5%'))
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    line = api.invoice_posts()[0]['Line'][0]
    assert line['SalesItemLineDetail']['TaxCodeRef'] == {'value': 'G5'}


def test_registered_item_carries_picked_code(app):
    svc, api = make_service([VAT20, GST5], tax_registered=True, picked=('G5', 'GST 5%'))
    svc.create_or_update_item(CONN, dict(ITEM_DATA))
    payload = api.item_posts()[0]
    assert payload['Taxable'] is True
    assert payload['SalesTaxCodeRef'] == {'value': 'G5'}


# ── 3. Registered + NO pick: fail closed, no POST ────────────────────────────
def test_registered_no_pick_blocks_invoice_with_no_post(app):
    svc, api = make_service([GST5], tax_registered=True, picked=None)
    result = svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert api.posts == []   # nothing was POSTed


def test_registered_no_pick_blocks_product_sync_with_no_post(app):
    svc, api = make_service([GST5], tax_registered=True, picked=None)
    invoice = types.SimpleNamespace(id=1)
    result = svc.sync_invoice_items_as_products(CONN, invoice)
    assert result['success'] is False
    assert result['code'] == 'TAX_CODE_UNRESOLVED'
    assert api.posts == []


# ── 4. The pick is authoritative (no rate-match), but must still exist ───────
def test_picked_code_attached_directly_no_rate_match(app):
    # The user's configured rate is 5, but they picked the 20% code 'V20'. The resolver
    # attaches it verbatim (it still exists in the file) — proving it does NOT rate-match.
    svc, _ = make_service([VAT20], tax_registered=True, tax_rate=5, picked=('V20', 'Standard 20%'))
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert code == {'value': 'V20', 'name': 'Standard 20%'}


def test_pick_for_other_provider_is_unresolved(app):
    # A pick made for Xero must not satisfy the QuickBooks resolver -> fail closed.
    svc, _ = make_service([GST5], tax_registered=True, picked=('OUTPUT', 'GST'),
                          picked_provider='xero')
    assert svc.resolve_output_tax(CONN) == (None, 'unresolved')


def test_registered_no_pick_is_unresolved(app):
    svc, _ = make_service([VAT20, GST5], tax_registered=True, picked=None)
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'unresolved'
    assert code is None


# ── 5. Stale pick (A1): the picked code is no longer in the file ─────────────
def test_stale_pick_nonempty_list_is_invalid(app):
    # Picked id 'GONE', but the file lists other codes -> genuinely stale -> invalid (re-pick).
    svc, _ = make_service([GST5], tax_registered=True, picked=('GONE', 'Old code'))
    assert svc.resolve_output_tax(CONN) == (None, 'invalid')


def test_stale_pick_empty_list_is_unresolved_not_invalid(app):
    # Picked id 'GONE' and the list is empty/unavailable -> transient-safe -> unresolved,
    # NOT invalid (a transient read failure must not masquerade as a stale ref).
    svc, _ = make_service([], tax_registered=True, picked=('GONE', 'Old code'))
    assert svc.resolve_output_tax(CONN) == (None, 'unresolved')


def test_stale_pick_blocks_invoice_with_invalid_code(app):
    svc, api = make_service([GST5], tax_registered=True, picked=('GONE', 'Old code'))
    result = svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_INVALID'
    assert api.posts == []   # nothing POSTed
