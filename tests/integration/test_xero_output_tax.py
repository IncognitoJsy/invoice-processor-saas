"""
Tests for Xero output-GST handling: XeroService.resolve_output_tax and the sync
payloads it drives (the Xero mirror of test_quickbooks_output_tax.py).

Behaviour (post tax-code PICKER, commit 5/7):
  1. Unregistered user -> lines push tax-exempt (no output GST): a named exempt TaxType
     when the org has one, else Xero's built-in 'NONE'.
  2. Registered user with a PICKED Xero TaxType -> lines carry that TaxType, attached
     DIRECTLY by its stored ref (no per-sync rate match).
  3. Registered user with NO pick -> sync BLOCKS (TAX_CODE_UNRESOLVED) and nothing is
     POSTed (fail closed).
  4. The pick is authoritative: the TaxType attached is exactly the picked ref regardless
     of what rates exist in the org, and a pick made for a different provider (e.g.
     QuickBooks) does NOT satisfy the Xero resolver.

Uses the integration `app` fixture; the HTTP layer (_make_request) is replaced with a
recording fake.
"""
import types

import pytest

from app.integrations.xero_service import XeroService

# Canned Xero TaxRate rows (as /TaxRates returns them) — used by the exempt path.
GST5 = {'Name': 'GST on Income', 'TaxType': 'GSTONINCOME', 'Status': 'ACTIVE',
        'EffectiveRate': 5.0, 'CanApplyToRevenue': True}
VAT20 = {'Name': '20% (VAT on Income)', 'TaxType': 'OUTPUT2', 'Status': 'ACTIVE',
         'EffectiveRate': 20.0, 'CanApplyToRevenue': True}
EXEMPT = {'Name': 'Exempt Income', 'TaxType': 'EXEMPTOUTPUT', 'Status': 'ACTIVE',
          'EffectiveRate': 0.0, 'CanApplyToRevenue': True}

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
                 country='Jersey', picked=None, picked_provider='xero'):
    """`picked` is (ref, name) for a stored Xero TaxType pick, or None."""
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


# ── 2. Registered + picked TaxType: lines carry the PICKED ref ───────────────
def test_registered_invoice_line_carries_picked_tax_type(app):
    svc, http = make_service([VAT20, GST5], tax_registered=True,
                             picked=('GSTONINCOME', 'GST on Income'))
    svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert _first_line_tax_type(http.invoice_posts()[0]) == 'GSTONINCOME'


def test_registered_quote_line_carries_picked_tax_type(app):
    svc, http = make_service([VAT20, GST5], tax_registered=True,
                             picked=('GSTONINCOME', 'GST on Income'))
    svc.create_quote(CONN, 'CUST1', list(LINE_ITEMS))
    assert http.quote_posts()[0]['Quotes'][0]['LineItems'][0]['TaxType'] == 'GSTONINCOME'


# ── 3. Registered + NO pick: fail closed, no POST ────────────────────────────
def test_registered_no_pick_blocks_invoice_with_no_post(app):
    svc, http = make_service([GST5], tax_registered=True, picked=None)
    result = svc.create_invoice(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert http.posts == []


def test_registered_no_pick_blocks_quote_with_no_post(app):
    svc, http = make_service([GST5], tax_registered=True, picked=None)
    result = svc.create_quote(CONN, 'CUST1', list(LINE_ITEMS))
    assert result.get('code') == 'TAX_CODE_UNRESOLVED'
    assert http.posts == []


# ── 4. The pick is authoritative ─────────────────────────────────────────────
def test_picked_tax_type_attached_directly(app):
    # The org lists only a 20% VAT rate, but the user picked 'GSTONINCOME'. The resolver
    # attaches the picked TaxType verbatim — it does NOT match against the org's rates.
    svc, _ = make_service([VAT20], tax_registered=True, picked=('GSTONINCOME', 'GST on Income'))
    tax_type, status = svc.resolve_output_tax(CONN)
    assert status == 'taxable'
    assert tax_type == 'GSTONINCOME'


def test_pick_for_other_provider_is_unresolved(app):
    # A pick made for QuickBooks must not satisfy the Xero resolver -> fail closed.
    svc, _ = make_service([GST5], tax_registered=True, picked=('2', 'GST'),
                          picked_provider='quickbooks')
    assert svc.resolve_output_tax(CONN) == (None, 'unresolved')


def test_registered_no_pick_is_unresolved(app):
    svc, _ = make_service([VAT20, GST5], tax_registered=True, picked=None)
    code, status = svc.resolve_output_tax(CONN)
    assert status == 'unresolved'
    assert code is None
