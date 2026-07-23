"""Pre-flight for the QBO "add to existing draft" path (fix-qb-draft-preflight).

Adding lines to an existing QBO invoice forces a FULL `Line` re-POST, and QBO re-validates every
echoed line on write. A line QBO tolerates as stored — most often an Amount hand-edited in the QBO
UI so it no longer equals Qty × UnitPrice — sinks the whole update with the opaque
"Amount calculation incorrect in the request" (the live prod failure on draft #4659 / Id 20958,
line DLT551500B10: Qty 30 × £18.50 shown as £297.00 instead of £555.00).

We refuse to silently rewrite or convert a line we did not create, so instead we PRE-FLIGHT the
draft and block cleanly, naming the offending line and showing the arithmetic; the UI offers
"sync to a new invoice instead" (force_new_invoice → use_existing_invoice=False). We also strip
QBO's auto-generated SubTotalLineDetail from the echo (a second trigger of the same rejection).

Classification under test: BLOCK mismatched Qty×Unit lines; STRIP SubTotal; pass clean / Amount-only
/ DescriptionOnly; BLOCK DiscountLineDetail, GroupLineDetail and unknown types (can't guarantee a
faithful verbatim round-trip once the SubTotal they pair with is stripped).
"""
import pytest

from app.integrations.quickbooks_service import QuickBooksService


def _svc():
    # Pure helpers need no OAuth config; skip __init__ to avoid requiring app config.
    return QuickBooksService.__new__(QuickBooksService)


def _sales_line(line_id, item, qty, unit, amount):
    return {'Id': str(line_id), 'DetailType': 'SalesItemLineDetail', 'Amount': amount,
            'SalesItemLineDetail': {'ItemRef': {'value': '1', 'name': item},
                                    'Qty': qty, 'UnitPrice': unit}}


class _Item:
    """Minimal stand-in for InvoiceItem in the itemised build."""
    def __init__(self, pn='A', qty=3, sp=7.0, desc='x'):
        self.part_number, self.quantity, self.selling_price, self.description = pn, qty, sp, desc


# ── _find_unappendable_lines: classification ────────────────────────────────────────────────
def test_mismatched_amount_line_is_flagged():
    inv = {'DocNumber': '4659', 'Id': '20958',
           'Line': [_sales_line(1, 'DLT551500B10', 30, 18.5, 297.0)]}
    problems = _svc()._find_unappendable_lines(inv)
    assert len(problems) == 1
    p = problems[0]
    assert p['reason'] == 'amount_mismatch'
    assert p['item'] == 'DLT551500B10'
    assert (p['qty'], p['unit'], p['amount'], p['expected']) == (30.0, 18.5, 297.0, 555.0)


def test_reconciling_line_is_ok():
    inv = {'Line': [_sales_line(2, '74SS2SS-B', 51, 16.73, 853.23)]}
    assert _svc()._find_unappendable_lines(inv) == []


def test_amount_only_line_is_ok():
    # Valid QBO flat-fee construct: no Qty/UnitPrice → nothing to reconcile, safe to echo.
    inv = {'Line': [{'Id': '3', 'DetailType': 'SalesItemLineDetail', 'Amount': 99.0,
                     'SalesItemLineDetail': {'ItemRef': {'value': '1', 'name': 'FLAT'}}}]}
    assert _svc()._find_unappendable_lines(inv) == []


def test_subtotal_and_description_are_ok():
    inv = {'Line': [{'DetailType': 'SubTotalLineDetail', 'Amount': 100.0, 'SubTotalLineDetail': {}},
                    {'Id': '5', 'DetailType': 'DescriptionOnly', 'Description': 'Header', 'Amount': 0}]}
    assert _svc()._find_unappendable_lines(inv) == []


def test_discount_line_is_blocked():
    inv = {'Line': [{'Id': '6', 'DetailType': 'DiscountLineDetail', 'Amount': 10.0,
                     'DiscountLineDetail': {'PercentBased': True, 'DiscountPercent': 10}}]}
    problems = _svc()._find_unappendable_lines(inv)
    assert len(problems) == 1
    assert problems[0]['reason'] == 'unsupported_line'
    assert problems[0]['detail_type'] == 'DiscountLineDetail'


def test_group_line_is_blocked():
    inv = {'Line': [{'Id': '7', 'DetailType': 'GroupLineDetail', 'GroupLineDetail': {}}]}
    problems = _svc()._find_unappendable_lines(inv)
    assert problems and problems[0]['reason'] == 'unsupported_line'
    assert problems[0]['detail_type'] == 'GroupLineDetail'


# ── _draft_not_appendable_block: clear message, not a QBO 400 ────────────────────────────────
def test_block_message_single():
    svc = _svc()
    inv = {'DocNumber': '4659', 'Id': '20958',
           'Line': [_sales_line(1, 'DLT551500B10', 30, 18.5, 297.0)]}
    res = svc._draft_not_appendable_block(inv, svc._find_unappendable_lines(inv))
    assert res['success'] is False
    assert res['code'] == 'DRAFT_NOT_APPENDABLE'
    assert res['can_create_new'] is True
    assert res['draft_doc_number'] == '4659'
    assert res['error'] == (
        "Can't add to draft #4659 — 'DLT551500B10' shows £297.00 but 30 × £18.50 = £555.00. "
        "Fix it in QuickBooks, or sync to a new invoice instead.")


def test_block_message_multi():
    svc = _svc()
    inv = {'DocNumber': '4659', 'Id': '20958', 'Line': [
        _sales_line(1, 'DLT551500B10', 30, 18.5, 297.0),
        _sales_line(2, 'FLCO-SS', 3, 4.0, 10.0)]}
    res = svc._draft_not_appendable_block(inv, svc._find_unappendable_lines(inv))
    assert res['error'].startswith("Can't add to draft #4659 — 2 lines can't be added:")
    assert "• 'DLT551500B10' shows £297.00 but 30 × £18.50 = £555.00" in res['error']
    assert "• 'FLCO-SS' shows £10.00 but 3 × £4.00 = £12.00" in res['error']
    assert res['error'].rstrip().endswith("sync to a new invoice instead.")


# ── SubTotal is stripped from the echoed array ──────────────────────────────────────────────
def test_add_items_strips_subtotal(app, monkeypatch):
    with app.app_context():
        svc = _svc()
        svc._output_tax_cache = None
        existing = {'Invoice': {'Id': '20958', 'SyncToken': '4', 'DocNumber': '4659', 'Line': [
            _sales_line(1, 'AAA', 2, 5.0, 10.0),
            {'DetailType': 'SubTotalLineDetail', 'Amount': 10.0, 'SubTotalLineDetail': {}},
        ]}}
        captured = {}

        def fake_api(conn, endpoint, method='GET', data=None):
            if method == 'GET':
                return existing
            captured['data'] = data
            return {'Invoice': {'Id': '20958'}}

        monkeypatch.setattr(svc, 'make_api_request', fake_api)
        monkeypatch.setattr(svc, 'resolve_output_tax', lambda conn: ({'value': '2'}, 'taxable'))

        svc.add_items_to_invoice(
            None, '20958',
            [{'item_id': '99', 'quantity': 3, 'unit_price': 7.0, 'description': 'New'}])

        sent = captured['data']['Line']
        assert all(l.get('DetailType') != 'SubTotalLineDetail' for l in sent)
        assert [l['DetailType'] for l in sent].count('SalesItemLineDetail') == 2  # kept + appended


# ── Orchestrator: block before any write, and the create-new fallback ───────────────────────
def _patch_syncables(monkeypatch, items):
    import app.services.sync_lines as sl
    monkeypatch.setattr(sl, 'get_syncable_line_items', lambda inv: items)


def test_sync_blocks_poisoned_draft_before_product_sync(app, monkeypatch):
    with app.app_context():
        svc = _svc()
        _patch_syncables(monkeypatch, [_Item()])
        poisoned = {'Id': '20958', 'DocNumber': '4659', 'Balance': 100, 'EmailStatus': '',
                    'Line': [_sales_line(1, 'DLT551500B10', 30, 18.5, 297.0)]}
        monkeypatch.setattr(svc, 'get_draft_invoices', lambda conn, cid: [poisoned])
        called = {'products': False}

        def _no_products(*a, **k):
            called['products'] = True
            return {}
        monkeypatch.setattr(svc, 'sync_invoice_items_as_products', _no_products)

        result = svc.sync_invoice_to_customer(None, object(), '2002')
        assert result['success'] is False
        assert result['code'] == 'DRAFT_NOT_APPENDABLE'
        assert result['can_create_new'] is True
        assert '4659' in '; '.join(result['errors'])   # route flattens errors → response 'error'
        assert called['products'] is False   # blocked BEFORE any catalog write


def test_sync_clean_draft_proceeds(app, monkeypatch):
    with app.app_context():
        svc = _svc()
        _patch_syncables(monkeypatch, [_Item(pn='A')])
        clean = {'Id': '20930', 'DocNumber': '4600', 'Balance': 100, 'EmailStatus': '',
                 'Line': [_sales_line(1, 'A', 2, 5.0, 10.0)]}
        monkeypatch.setattr(svc, 'get_draft_invoices', lambda conn, cid: [clean])
        monkeypatch.setattr(svc, 'sync_invoice_items_as_products',
                            lambda conn, inv: {'synced': 1, 'failed': 0,
                                               'products': [{'part_number': 'A', 'qb_id': '99'}],
                                               'errors': []})
        added = {'n': 0}

        def _add(conn, iid, line_items):
            added['n'] += 1
            return {'Invoice': {'Id': '20930', 'DocNumber': '4600'}}
        monkeypatch.setattr(svc, 'add_items_to_invoice', _add)

        result = svc.sync_invoice_to_customer(None, object(), '2002')
        assert result['success'] is True
        assert result['invoice_action'] == 'added_to_existing'
        assert added['n'] == 1


def test_force_new_bypasses_draft(app, monkeypatch):
    with app.app_context():
        svc = _svc()
        _patch_syncables(monkeypatch, [_Item(pn='A')])
        drafts = {'n': 0}

        def _drafts(conn, cid):
            drafts['n'] += 1
            return [{'Id': 'x', 'DocNumber': 'y', 'Balance': 1, 'EmailStatus': '',
                     'Line': [_sales_line(1, 'A', 30, 18.5, 297.0)]}]
        monkeypatch.setattr(svc, 'get_draft_invoices', _drafts)
        monkeypatch.setattr(svc, 'sync_invoice_items_as_products',
                            lambda conn, inv: {'synced': 1, 'failed': 0,
                                               'products': [{'part_number': 'A', 'qb_id': '99'}],
                                               'errors': []})
        created = {'n': 0}

        def _create(conn, cid, line_items, memo=None):
            created['n'] += 1
            return {'Invoice': {'Id': 'NEW', 'DocNumber': '9999'}}
        monkeypatch.setattr(svc, 'create_invoice', _create)

        result = svc.sync_invoice_to_customer(None, object(), '2002', use_existing_invoice=False)
        assert result['success'] is True
        assert result['invoice_action'] == 'created_new'
        assert drafts['n'] == 0        # draft never even looked up
        assert created['n'] == 1
