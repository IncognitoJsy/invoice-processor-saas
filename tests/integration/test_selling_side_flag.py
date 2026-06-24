"""Phase 2 (#3): selling-side plausibility flag in save_invoice_to_db.

A line whose implied markup is implausibly high AND whose price is above the supplier
counter price blocks (validation_errors / needs_review) so it can't sync silently — the
selling-side analogue of the arithmetic gate. The "above counter" AND deliberately spares
legit high-margin-at-counter pricing (the false-positive risk).

Each fixture is a single clean-arithmetic line (net = cost, tax 0, gross = cost) so ONLY the
selling-side check can flag it — never the arithmetic validator.
"""
import json

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    monkeypatch.setattr(upload_module, 'current_user', user)


def _inv(part, cost, sell, listp):
    return {
        'supplier': 'Wholesale Electrics', 'invoice_number': f'SELLFLAG-{part}',
        'items': [{
            'part_number': part, 'quantity': 1, 'unit_price': cost, 'total_amount': cost,
            'cost_per_item': cost, 'selling_price': sell, 'original_unit_price': listp,
            'calculated_selling_price': sell, 'markup_percent': 0, 'profit_per_item': sell - cost,
        }],
        'total_ex_tax': cost, 'tax_amount': 0, 'total_inc_tax': cost, 'tax_rate': 0,
    }


def test_selling_side_blocks_when_above_counter(app, user):
    # cost 5.51, sell 47.82 (768% over cost) and 47.82 >> list 5.25 -> blocks.
    inv = save_invoice_to_db(_inv('PXBAD', 5.51, 47.82, 5.25), 's.pdf', user.id)
    assert inv.validation_errors is not None
    reasons = json.loads(inv.validation_errors)
    assert any('over cost' in r and 'counter' in r for r in reasons)
    assert inv.needs_review is True


def test_legit_high_margin_at_counter_not_flagged(app, user):
    # cost 0.95, sell 8.50 (795% over cost) BUT 8.50 <= counter/list 9.00 -> NOT flagged.
    inv = save_invoice_to_db(_inv('YDT', 0.95, 8.50, 9.00), 's.pdf', user.id)
    assert inv.validation_errors is None
    assert inv.needs_review is False


def test_no_list_absurd_markup_still_blocks(app, user):
    # cost 2.00, sell 20.00 (900% over cost), no list -> treated as above counter -> blocks.
    inv = save_invoice_to_db(_inv('NOLIST', 2.00, 20.00, 0), 's.pdf', user.id)
    assert inv.validation_errors is not None
    assert inv.needs_review is True


def test_normal_markup_not_flagged(app, user):
    # cost 10, sell 12 (20%) -> well under threshold, clean.
    inv = save_invoice_to_db(_inv('NORMAL', 10.00, 12.00, 12.00), 's.pdf', user.id)
    assert inv.validation_errors is None
    assert inv.needs_review is False
