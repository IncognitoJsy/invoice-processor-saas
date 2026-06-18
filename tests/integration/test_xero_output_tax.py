"""
Tests for Xero output-GST handling: XeroService.resolve_output_tax and the sync
payloads it drives (Step 3b — the Xero mirror of test_quickbooks_output_tax.py).

Covers the same four behaviours:
  1. Unregistered user -> lines push tax-exempt (no output GST): a named exempt
     TaxType when the org has one, else Xero's built-in 'NONE'.
  2. Registered user -> lines carry the GST TaxType.
  3. Registered user + no resolvable rate -> sync BLOCKS (TAX_CODE_UNRESOLVED) and
     nothing is POSTed (fail closed).
  4. Region/rate selection -> a Jersey 5% GST rate is picked over a 20% VAT rate
     also present (by rate, not list order), and a sales (revenue) rate is chosen
     over a purchase (input) rate of the same percentage.

Xero TaxRates carry explicit numeric rates, so the fakes include EffectiveRate /
CanApplyToRevenue as the real API does. Uses the integration `app` fixture; the
HTTP layer (_make_request) is replaced with a recording fake.
"""
import types

import pytest

from app.integrations.xero_service import XeroService

# Canned Xero TaxRate rows (as /TaxRates returns them).
GST5 = {'Name': 'GST on Income', 'TaxType': 'GSTONINCOME', 'Status': 'ACTIVE',
        'EffectiveRate': 5.0, 'CanApplyToRevenue': True}
VAT20 = {'Name': '20% (VAT on Income)', 'TaxType': 'OUTPUT2', 'Status': 'ACTIVE',
         'EffectiveRate': 20.0, 'CanApplyToRevenue': True}
EXEMPT = {'Name': 'Exempt Income', 'TaxType': 'EXEMPTOUTPUT', 'Status': 'ACTIVE',
          'EffectiveRate': 0.0, 'CanApplyToRevenue': True}
GST5_INPUT = {'Name': 'GST on Purchases', 'TaxType': 'GSTONPURCHASES', 'Status': 'ACTIVE',
              'EffectiveRate': 5.0, 'CanApplyToRevenue': False}

LINE_ITEMS = [{'description': 'x', 'quantity': 2, 'unit_price': 10.0,
               'account_code': '200', 'item_code': 'PART1'}]


class FakeHTTP:
    """Stand-in for _make_request: routes by endpoint, records POST payloads."""

    def __init__(self, tax_rates):
        self.tax_rates = tax_rates
        self.posts = []  # list of (endpoint, data) for every POST

    def __call__(self, method, endpoint, connection, data=None):
        if method == 'POST':
            self.posts.append((endpoint, data))
            if endpoint.startswith('/Invoices'):
                return {'Invoices': [{'InvoiceID': 'XI', 'InvoiceNumber': 'INV-1',
                                      **(data or {}).get('Invoices', [{}])[0]}]}
            if endpoint.startswith('/Quotes'):
                return {'Quotes': [{'QuoteID': 'XQ', 'QuoteNumber': 'QU-1',
                                    **(data or {}).get('Quotes', [{}])[0]}]}
            if endpoint.startswith('/Items'):
                return {'Items': [{'ItemID': 'IT', **(data or {}).get('Items', [{}])[0]}]}
            return {}
        # GET
        if endpoint.startswith('/TaxRates'):
            return {'TaxRates': list(self.tax_rates)}
        return {}

    def invoice_posts(self):
        return [d for (ep, d) in self.posts if ep.startswith('/Invoices')]

    def quote_posts(self):
        return [d for (ep, d) in self.posts if ep.startswith('/Quotes')]


def make_service(tax_rates, *, tax_registered=True, tax_type='GST', tax_rate=5,
                 country='Jersey'):
    user = types.SimpleNamespace(
        id=1,
        tax_registered=tax_registered,
        tax_type=tax_type,
        tax_rate=tax_rate,
        country=country,
        business_address_country=country,
    )
    svc = XeroService(user)
    http = FakeHTTP(tax_rates)
    svc._make_request = http
    return svc, http


CONN = object()  # the fake ignores the connection


def _first_line_tax_type(invoice_post):
    return invoice_post['Invoices'][0]['LineItems'][0]['TaxType']


# ── 1. Unregistered: no output GST ───────────────────────────────────────────
def test_unregistered_invoice_uses_exempt_tax_type(app):
    svc, http = make_service([GST5, EXEMPT], tax_registered=False, tax_type='', tax_rate=0)
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert _first_line_tax_type(http.invoice_posts()[0]) == 'EXEMPTOUTPUT'  # not the 5% GST type


def test_unregistered_invoice_falls_back_to_none(app):
    svc, http = make_service([GST5], tax_registered=False, tax_type='', tax_rate=0)
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert _first_line_tax_type(http.invoice_posts()[0]) == 'NONE'  # Xero's built-in no-tax type


# ── 2. Registered: lines carry the GST tax type ──────────────────────────────
def test_registered_invoice_line_carries_gst_tax_type(app):
    svc, http = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert _first_line_tax_type(http.invoice_posts()[0]) == 'GSTONINCOME'


def test_registered_quote_line_carries_gst_tax_type(app):
    svc, http = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    svc.create_quote(CONN, 'CUST1', list(LINE_ITEMS))
    assert http.quote_posts()[0]['Quotes'][0]['LineItems'][0]['TaxType'] == 'GSTONINCOME'


# ── 3. Registered + no resolvable rate: fail closed, no POST ─────────────────
def test_registered_no_rate_blocks_invoice_with_no_post(app):
    svc, http = make_service([], tax_registered=True, tax_type='GST', tax_rate=5)
    result = svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert http.posts == []


def test_registered_no_rate_blocks_quote_with_no_post(app):
    svc, http = make_service([], tax_registered=True, tax_type='GST', tax_rate=5)
    result = svc.create_quote(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert http.posts == []


# ── 4. Region/rate selection ─────────────────────────────────────────────────
def test_jersey_gst_picked_over_vat_by_rate(app):
    # VAT listed FIRST to prove it is rate-matched, not first-wins.
    svc, _ = make_service([VAT20, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    tax_type, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert tax_type == 'GSTONINCOME'


def test_region_drives_gst_when_tax_type_and_rate_blank(app):
    svc, _ = make_service([VAT20, GST5], tax_registered=True, tax_type='', tax_rate=0,
                          country='Jersey')
    tax_type, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert tax_type == 'GSTONINCOME'


def test_sales_rate_chosen_over_purchase_rate_same_percent(app):
    # Both 5%, but only the revenue-applicable (sales) one may be used on an invoice.
    svc, _ = make_service([GST5_INPUT, GST5], tax_registered=True, tax_type='GST', tax_rate=5)
    tax_type, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert tax_type == 'GSTONINCOME'  # not GSTONPURCHASES
