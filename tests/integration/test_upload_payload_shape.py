"""Phase 3: the upload-result payload now serializes the SAVED InvoiceItem rows via to_dict()
instead of the transient parser dicts. Pins the payload shape so the four features have data and
nothing the upload template reads goes missing.

Replicates the exact route serialization
    items = sorted((it.to_dict() for it in saved_invoice.items), key=lambda d: d['id'])
against a saved invoice, and asserts to_dict() is a superset of what the upload template renders
plus the four-feature fields the parser dict omitted.
"""
import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    monkeypatch.setattr(upload_module, 'current_user', user)


def _data():
    # two clean lines (net 50, +20% tax = 60) so save isn't blocked; part numbers + per-unit fields.
    return {
        'supplier': 'Wholesale Electrics', 'invoice_number': 'UP-SHAPE-1',
        'items': [
            {'part_number': 'A', 'description': 'Item A', 'quantity': 2, 'unit_price': 10,
             'total_amount': 20, 'cost_per_item': 10, 'selling_price': 12,
             'original_unit_price': 10, 'markup_percent': 20, 'profit_per_item': 2},
            {'part_number': 'B', 'description': 'Item B', 'quantity': 1, 'unit_price': 30,
             'total_amount': 30, 'cost_per_item': 30, 'selling_price': 36,
             'original_unit_price': 30, 'markup_percent': 20, 'profit_per_item': 6},
        ],
        'total_ex_tax': 50, 'tax_amount': 10, 'total_inc_tax': 60, 'tax_rate': 20,
    }


# fields the upload-result template renders / sums on
_DISPLAY_FIELDS = ('part_number', 'description', 'quantity', 'cost_per_item',
                   'selling_price', 'profit_per_item', 'total_amount')
# the four-feature fields the old parser dict omitted
_FEATURE_FIELDS = ('id', 'markup_percent', 'price_overridden', 'created_at', 'updated_at')


def test_upload_payload_serializes_saved_rows(app, user):
    inv = save_invoice_to_db(_data(), 'f.pdf', user.id)
    # exact expression the upload route now uses
    payload_items = sorted((it.to_dict() for it in inv.items), key=lambda d: d['id'])

    assert len(payload_items) == 2
    for d in payload_items:
        for k in _DISPLAY_FIELDS:
            assert k in d, f"upload template reads {k} but to_dict() omits it"
        for k in _FEATURE_FIELDS:
            assert k in d, f"four-feature field {k} missing from payload"

    # carries real saved values; not overridden on a fresh parse
    first = payload_items[0]
    assert first['part_number'] == 'A'
    assert first['price_overridden'] is False
    assert float(first['selling_price']) == 12.0
    assert isinstance(first['id'], int)


def test_payload_total_matches_saved_lines(app, user):
    inv = save_invoice_to_db(_data(), 'f.pdf', user.id)
    payload_items = sorted((it.to_dict() for it in inv.items), key=lambda d: d['id'])
    total = sum(it.get('total_amount', 0) for it in payload_items)   # route's 'total'
    assert float(total) == 50.0   # 20 + 30, the line-cost total


def test_no_template_field_relies_on_parser_only_keys(app, user):
    """The template never reads parser-only keys absent from to_dict() (e.g. 'discount');
    to_dict exposes 'discount_percent' instead — guard against a silent rename break."""
    inv = save_invoice_to_db(_data(), 'f.pdf', user.id)
    d = inv.items.first().to_dict()
    assert 'discount_percent' in d
    assert 'discount' not in d   # parser-dict key name; template must not depend on it
