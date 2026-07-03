"""Phase 2: sync must honour the `excluded` soft-remove flag.

An excluded (soft-removed) line must touch NEITHER the QB Products & Services catalog NOR the QB
customer invoice — the same all-or-nothing discipline as the validation/tax sync gates. Every test
mocks the HTTP layer (QuickBooksService.make_api_request) and asserts the excluded SKU appears in
zero catalog writes and zero invoice lines, while the remaining line syncs normally and the QB
invoice's own line total matches the Phase-1 recomputed header.
"""
import json
from decimal import Decimal

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.models.invoice import InvoiceItem
from app.services.invoice_totals import recompute_invoice_totals
from app.integrations.quickbooks_service import QuickBooksService

EXCLUDED_SKU = 'WMSS82'
EXCLUDED_DESC = 'Back box'
KEPT_SKU = 'MTN150'


def _clean_two_line():
    # Two clean lines: net 20 + 30 = 50; 50 + 10 (20%) = 60 → validator passes, reconciler no-op.
    return {
        'supplier': 'CEF', 'invoice_number': 'INV-EXCL', 'tax_rate': 20,
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
    """Clean invoice, then soft-remove the WMSS82 line and recompute the header (Phase 1)."""
    inv = save_invoice_to_db(_clean_two_line(), 'e.pdf', user.id)
    assert inv.validation_errors is None
    it = InvoiceItem.query.filter_by(invoice_id=inv.id, part_number=EXCLUDED_SKU).first()
    it.excluded = True
    db.session.commit()
    recompute_invoice_totals(inv)
    db.session.commit()
    # Header now reflects only the kept line (30 net / 45 selling); stays clean (no re-validate).
    assert inv.total_ex_tax == Decimal('30.00')
    assert inv.total_selling == Decimal('45.00')
    assert inv.validation_errors is None
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


def _capture(monkeypatch):
    """Mock the QB HTTP layer; record every (endpoint, method, data). Return the calls list."""
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
    # Registered user with a resolved output tax code (skip the live tax-code lookup).
    monkeypatch.setattr(QuickBooksService, 'resolve_output_tax', lambda self, conn: ({'value': '2'}, 'ok'))
    return calls


def _item_posts(calls):
    return [data for (ep, m, data) in calls if ep == 'item' and m == 'POST']


def _invoice_posts(calls):
    return [data for (ep, m, data) in calls if ep == 'invoice' and m == 'POST']


def _excluded_sku_appears_anywhere(calls):
    blob = json.dumps([data for (_e, _m, data) in calls if data is not None])
    return EXCLUDED_SKU in blob or EXCLUDED_DESC in blob


# ── Catalog path: excluded SKU gets ZERO catalog writes ──────────────────────────────────
def test_catalog_skips_excluded_line(app, user, excluded_invoice, qb_conn, monkeypatch):
    calls = _capture(monkeypatch)
    res = QuickBooksService(user).sync_invoice_items_as_products(qb_conn, excluded_invoice)

    posts = _item_posts(calls)
    assert res['synced'] == 1                                  # only the kept line
    assert len(posts) == 1
    assert (posts[0].get('Sku') or posts[0].get('Name')) == KEPT_SKU
    assert not any((p.get('Sku') == EXCLUDED_SKU or p.get('Name') == EXCLUDED_SKU) for p in posts)


# ── Full path: excluded SKU in NEITHER the catalog NOR the invoice; header total matches ──
def test_full_sync_excludes_line_from_invoice_and_catalog(app, user, excluded_invoice, qb_conn, monkeypatch):
    calls = _capture(monkeypatch)
    res = QuickBooksService(user).sync_invoice_to_customer(
        qb_conn, excluded_invoice, customer_id='1', use_existing_invoice=False, sync_mode='itemised')

    # Catalog: one write, for the kept SKU only.
    item_posts = _item_posts(calls)
    assert len(item_posts) == 1
    assert (item_posts[0].get('Sku') or item_posts[0].get('Name')) == KEPT_SKU

    # Invoice: exactly one, with a single line — the kept SKU. No line for the excluded SKU.
    inv_posts = _invoice_posts(calls)
    assert len(inv_posts) == 1
    lines = inv_posts[0]['Line']
    assert len(lines) == 1
    assert lines[0]['SalesItemLineDetail']['ItemRef']['value'] == f'itm-{KEPT_SKU}'

    # The excluded SKU/description appears in NO payload at all (catalog or invoice).
    assert not _excluded_sku_appears_anywhere(calls)

    # QB invoice line total is internally consistent with the Phase-1 recomputed header (45.00).
    total_pushed = sum(l['Amount'] for l in lines)
    assert total_pushed == float(excluded_invoice.total_selling) == 45.0
    assert res['qb_invoice_id'] == 'QBINV1'
