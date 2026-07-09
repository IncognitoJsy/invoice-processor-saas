"""Phase 2: a DEDUCTION line (total_amount < 0) must NOT push to the customer invoice OR the product
catalog, on BOTH QuickBooks and Xero — through the SAME shared gate (get_syncable_line_items) the
`excluded` feature uses. Mirrors test_invoice_line_excluded_sync.py / _xero.py.

CRITICAL invariant also asserted here: the deduction stays COUNTED in the header net (the invoice
keeps reconciling and does NOT re-block) — it is only filtered from the customer push. Validation is
never weakened; recompute keeps the -30 in the net, and the deduction's selling_price 0 means
total_selling still equals the sum of the pushed positive lines.
"""
import json
from decimal import Decimal
from datetime import datetime

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.services.sync_lines import get_syncable_line_items, is_deduction_line
from app.integrations.quickbooks_service import QuickBooksService
from app.integrations.xero_service import XeroService

MAT_SKU = 'TPSM0450'          # kept, marked up
FAN_SKU = 'SIL100T'           # kept, marked up
DEDUCT_SKU = 'FH01SENSOR'     # deduction — must NEVER reach a provider
DEDUCT_DESC = 'VARME sensor removed from kit'


def _invoice_with_deduction():
    # net = 100 - 30 + 50 = 120; +20% tax = 24; gross 144 → ties out, validator passes.
    # The deduction is cost-only: total_amount -30, selling_price 0 (contributes 0 to total_selling).
    return {
        'supplier': 'Wholesale Electrics', 'invoice_number': 'INV-DEDUCT', 'tax_rate': 20,
        'total_ex_tax': 120, 'tax_amount': 24, 'total_inc_tax': 144,
        'items': [
            {'part_number': MAT_SKU, 'description': 'Cable mat kit', 'quantity': 1, 'unit_price': 100,
             'total_amount': 100, 'cost_per_item': 100, 'selling_price': 150, 'original_unit_price': 100,
             'markup_percent': 50, 'profit_per_item': 50},
            {'part_number': DEDUCT_SKU, 'description': DEDUCT_DESC, 'quantity': -1, 'unit_price': 30,
             'total_amount': -30, 'cost_per_item': 30, 'selling_price': 0, 'original_unit_price': 30,
             'markup_percent': 0, 'profit_per_item': 0},
            {'part_number': FAN_SKU, 'description': 'Extractor fan', 'quantity': 1, 'unit_price': 50,
             'total_amount': 50, 'cost_per_item': 50, 'selling_price': 75, 'original_unit_price': 50,
             'markup_percent': 50, 'profit_per_item': 25},
        ],
    }


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    monkeypatch.setattr(upload_module, 'current_user', user)


@pytest.fixture
def deduction_invoice(app, db, user):
    inv = save_invoice_to_db(_invoice_with_deduction(), 'd.pdf', user.id)
    # Reconciliation invariant: the -30 is COUNTED, the invoice is clean (not blocked).
    assert inv.validation_errors is None
    assert inv.total_ex_tax == Decimal('120.00')       # deduction counted in the net
    assert inv.total_selling == Decimal('225.00')      # 150 + 0 + 75 (deduction bills nothing)
    assert inv.items_count == 3                          # all three lines retained in the record
    return inv


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
    from app.models.xero import XeroConnection
    c = XeroConnection(user_id=user.id, tenant_id='t', access_token='a', refresh_token='r',
                       token_expires_at=datetime.utcnow(), is_active=True,
                       default_expense_account_code='200', default_sales_account_code='201')
    db.session.add(c)
    db.session.commit()
    return c


# ── The gate itself ──────────────────────────────────────────────────────────────────────
def test_gate_filters_deduction_line(deduction_invoice):
    syncable = get_syncable_line_items(deduction_invoice)
    skus = {i.part_number for i in syncable}
    assert skus == {MAT_SKU, FAN_SKU}                   # deduction absent
    assert DEDUCT_SKU not in skus
    assert not any(is_deduction_line(i) for i in syncable)
    # ...but the deduction row still exists on the invoice (retained, just not syncable).
    assert any(is_deduction_line(i) for i in deduction_invoice.items)


# ── QuickBooks ───────────────────────────────────────────────────────────────────────────
def _qb_capture(monkeypatch):
    calls = []

    def fake(self, conn, endpoint, method='GET', data=None):
        calls.append((endpoint, method, data))
        if endpoint == 'item' and method == 'POST':
            key = (data or {}).get('Sku') or (data or {}).get('Name')
            return {'Item': {'Id': f'itm-{key}', 'Name': (data or {}).get('Name')}}
        if endpoint == 'invoice' and method == 'POST':
            return {'Invoice': {'Id': 'QBINV1', 'DocNumber': 'DOC1'}}
        return {}
    monkeypatch.setattr(QuickBooksService, 'make_api_request', fake)
    monkeypatch.setattr(QuickBooksService, 'resolve_output_tax', lambda self, conn: ({'value': '2'}, 'ok'))
    return calls


def _deduction_in_payloads(calls):
    blob = json.dumps([c[2] for c in calls if c[2] is not None])
    return DEDUCT_SKU in blob or DEDUCT_DESC in blob


def test_qb_catalog_skips_deduction_line(app, user, deduction_invoice, qb_conn, monkeypatch):
    calls = _qb_capture(monkeypatch)
    res = QuickBooksService(user).sync_invoice_items_as_products(qb_conn, deduction_invoice)

    posts = [d for (ep, m, d) in calls if ep == 'item' and m == 'POST']
    assert res['synced'] == 2                           # both kept lines, not the deduction
    assert {(p.get('Sku') or p.get('Name')) for p in posts} == {MAT_SKU, FAN_SKU}
    assert not _deduction_in_payloads(calls)


def test_qb_full_sync_excludes_deduction_from_invoice_and_catalog(app, user, deduction_invoice, qb_conn, monkeypatch):
    calls = _qb_capture(monkeypatch)
    res = QuickBooksService(user).sync_invoice_to_customer(
        qb_conn, deduction_invoice, customer_id='1', use_existing_invoice=False, sync_mode='itemised')

    item_posts = [d for (ep, m, d) in calls if ep == 'item' and m == 'POST']
    assert {(p.get('Sku') or p.get('Name')) for p in item_posts} == {MAT_SKU, FAN_SKU}

    inv_posts = [d for (ep, m, d) in calls if ep == 'invoice' and m == 'POST']
    assert len(inv_posts) == 1
    lines = inv_posts[0]['Line']
    assert len(lines) == 2                              # exactly the two positive lines
    assert {l['SalesItemLineDetail']['ItemRef']['value'] for l in lines} == {f'itm-{MAT_SKU}', f'itm-{FAN_SKU}'}

    assert not _deduction_in_payloads(calls)            # deduction in NO payload (catalog or invoice)

    # QB invoice line total matches the header total_selling (deduction billed nothing).
    assert sum(l['Amount'] for l in lines) == float(deduction_invoice.total_selling) == 225.0
    assert res['qb_invoice_id'] == 'QBINV1'


# ── Xero ─────────────────────────────────────────────────────────────────────────────────
def _xero_capture(monkeypatch):
    calls = []

    def fake(self, method, path, connection, data=None):
        calls.append((method, path, data))
        if method == 'GET' and path == '/Items':
            return {'Items': []}
        if method == 'POST' and path == '/Items':
            code = (data or {}).get('Items', [{}])[0].get('Code')
            return {'Items': [{'ItemID': f'itm-{code}', 'Code': code}]}
        if method == 'POST' and path == '/Invoices':
            return {'Invoices': [{'InvoiceID': 'XINV1', 'InvoiceNumber': 'INV-1'}]}
        return {}
    monkeypatch.setattr(XeroService, '_make_request', fake)
    monkeypatch.setattr(XeroService, 'resolve_output_tax', lambda self, conn: ('OUTPUT2', 'ok'))
    return calls


def _xero_deduction_in_payloads(calls):
    blob = json.dumps([d for (_m, _p, d) in calls if d is not None])
    return DEDUCT_SKU in blob or DEDUCT_DESC in blob


def test_xero_catalog_skips_deduction_line(app, user, deduction_invoice, xero_conn, monkeypatch):
    calls = _xero_capture(monkeypatch)
    res = XeroService(user).sync_products_to_items(xero_conn, deduction_invoice)

    posts = [d for (m, p, d) in calls if m == 'POST' and p == '/Items']
    assert res['synced'] == 2
    assert {p['Items'][0]['Code'] for p in posts} == {MAT_SKU, FAN_SKU}
    assert not _xero_deduction_in_payloads(calls)


def test_xero_full_sync_excludes_deduction_from_invoice_and_catalog(app, user, deduction_invoice, xero_conn, monkeypatch):
    calls = _xero_capture(monkeypatch)
    res = XeroService(user).sync_to_customer_invoice(
        xero_conn, deduction_invoice, customer_contact_id='c1', use_existing_invoice=False)

    item_posts = [d for (m, p, d) in calls if m == 'POST' and p == '/Items']
    assert {p['Items'][0]['Code'] for p in item_posts} == {MAT_SKU, FAN_SKU}

    inv_posts = [d for (m, p, d) in calls if m == 'POST' and p == '/Invoices']
    assert len(inv_posts) == 1
    lines = inv_posts[0]['Invoices'][0]['LineItems']
    assert len(lines) == 2
    assert {l['ItemCode'] for l in lines} == {MAT_SKU, FAN_SKU}

    assert not _xero_deduction_in_payloads(calls)

    total_pushed = sum(float(l['UnitAmount']) * float(l['Quantity']) for l in lines)
    assert total_pushed == float(deduction_invoice.total_selling) == 225.0
    assert res['success'] is True
    assert res['xero_invoice_id'] == 'XINV1'
