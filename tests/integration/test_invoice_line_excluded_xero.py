"""Xero parity for the `excluded` soft-remove flag (mirrors test_invoice_line_excluded_sync.py for QB).

An excluded line must touch NEITHER the Xero catalog (Items) NOR the Xero customer invoice — the
same shared exclusion gate (get_syncable_line_items) QB uses. Mocks the Xero HTTP layer
(XeroService._make_request) and asserts the excluded SKU appears in zero Item writes and zero
invoice lines, while the remaining line syncs and the Xero invoice's line total matches the
Phase-1 recomputed header.
"""
import json
from decimal import Decimal
from datetime import datetime

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.models.invoice import InvoiceItem
from app.services.invoice_totals import recompute_invoice_totals
from app.integrations.xero_service import XeroService

EXCLUDED_SKU = 'WMSS82'
EXCLUDED_DESC = 'Back box'
KEPT_SKU = 'MTN150'


def _clean_two_line():
    # net 20 + 30 = 50; 50 + 10 (20%) = 60 → validator passes, reconciler no-op.
    return {
        'supplier': 'CEF', 'invoice_number': 'INV-XERO-EXCL', 'tax_rate': 20,
        'total_ex_tax': 50, 'tax_amount': 10, 'total_inc_tax': 60,
        'items': [
            {'part_number': EXCLUDED_SKU, 'description': EXCLUDED_DESC, 'quantity': 2, 'unit_price': 10,
             'total_amount': 20, 'cost_per_item': 10, 'selling_price': 15, 'original_unit_price': 10,
             'markup_percent': 50, 'profit_per_item': 5},
            {'part_number': KEPT_SKU, 'description': 'Trunking', 'quantity': 1, 'unit_price': 30,
             'total_amount': 30, 'cost_per_item': 30, 'selling_price': 45, 'original_unit_price': 30,
             'markup_percent': 50, 'profit_per_item': 15},
        ],
    }


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    monkeypatch.setattr(upload_module, 'current_user', user)


@pytest.fixture
def excluded_invoice(app, db, user):
    inv = save_invoice_to_db(_clean_two_line(), 'e.pdf', user.id)
    assert inv.validation_errors is None
    it = InvoiceItem.query.filter_by(invoice_id=inv.id, part_number=EXCLUDED_SKU).first()
    it.excluded = True
    db.session.commit()
    recompute_invoice_totals(inv)
    db.session.commit()
    assert inv.total_ex_tax == Decimal('30.00')
    assert inv.total_selling == Decimal('45.00')
    return inv


@pytest.fixture
def xero_conn(db, user):
    from app.models.xero import XeroConnection
    c = XeroConnection(user_id=user.id, tenant_id='t', access_token='a', refresh_token='r',
                       token_expires_at=datetime.utcnow(), is_active=True,
                       default_expense_account_code='200', default_sales_account_code='201')
    db.session.add(c)
    db.session.commit()
    return c


def _capture(monkeypatch):
    calls = []

    def fake(self, method, path, connection, data=None):
        calls.append((method, path, data))
        if method == 'GET' and path == '/Items':
            return {'Items': []}                       # no existing item → create
        if method == 'POST' and path == '/Items':
            code = (data or {}).get('Items', [{}])[0].get('Code')
            return {'Items': [{'ItemID': f'itm-{code}', 'Code': code}]}
        if method == 'POST' and path == '/Invoices':
            return {'Invoices': [{'InvoiceID': 'XINV1', 'InvoiceNumber': 'INV-1'}]}
        return {}
    monkeypatch.setattr(XeroService, '_make_request', fake)
    monkeypatch.setattr(XeroService, 'resolve_output_tax', lambda self, conn: ('OUTPUT2', 'ok'))
    return calls


def _item_posts(calls):
    return [d for (m, p, d) in calls if m == 'POST' and p == '/Items']


def _invoice_posts(calls):
    return [d for (m, p, d) in calls if m == 'POST' and p == '/Invoices']


def _excluded_sku_appears_anywhere(calls):
    blob = json.dumps([d for (_m, _p, d) in calls if d is not None])
    return EXCLUDED_SKU in blob or EXCLUDED_DESC in blob


# ── Catalog (Items) path: excluded SKU gets ZERO catalog writes ──────────────────────────
def test_xero_catalog_skips_excluded_line(app, user, excluded_invoice, xero_conn, monkeypatch):
    calls = _capture(monkeypatch)
    res = XeroService(user).sync_products_to_items(xero_conn, excluded_invoice)

    posts = _item_posts(calls)
    assert res['synced'] == 1
    assert len(posts) == 1
    assert posts[0]['Items'][0]['Code'] == KEPT_SKU
    assert not any(p['Items'][0]['Code'] == EXCLUDED_SKU for p in posts)


# ── Full path: excluded SKU in NEITHER the catalog NOR the invoice; header total matches ──
def test_xero_full_sync_excludes_line_from_invoice_and_catalog(app, user, excluded_invoice, xero_conn, monkeypatch):
    calls = _capture(monkeypatch)
    res = XeroService(user).sync_to_customer_invoice(
        xero_conn, excluded_invoice, customer_contact_id='c1', use_existing_invoice=False)

    # Catalog: one Item write, the kept SKU only.
    item_posts = _item_posts(calls)
    assert len(item_posts) == 1
    assert item_posts[0]['Items'][0]['Code'] == KEPT_SKU

    # Invoice: exactly one, with a single line — the kept SKU. No line for the excluded SKU.
    inv_posts = _invoice_posts(calls)
    assert len(inv_posts) == 1
    lines = inv_posts[0]['Invoices'][0]['LineItems']
    assert len(lines) == 1
    assert lines[0]['ItemCode'] == KEPT_SKU

    # Excluded SKU/description appears in NO payload (catalog or invoice).
    assert not _excluded_sku_appears_anywhere(calls)

    # Xero sums the pushed lines → its invoice total matches the recomputed header (45.00).
    total_pushed = sum(float(l['UnitAmount']) * float(l['Quantity']) for l in lines)
    assert total_pushed == float(excluded_invoice.total_selling) == 45.0
    assert res['success'] is True
    assert res['xero_invoice_id'] == 'XINV1'
