"""Invoice totals reconcile to the penny under the Decimal money migration.

The LINE is the authority for totals:
  line_cost = total_amount, line_selling = money(selling_per_unit * qty),
  line_profit = line_selling - line_cost  =>  total_profit == total_selling - total_cost.

profit_per_item stays the per-unit view and may differ from the line profit by a
penny on quantities that don't divide cleanly — which is exactly why the line, not
the per-unit figure, is summed for totals.
"""
from decimal import Decimal

import pytest

from app.web import upload as upload_module
from app.web.upload import save_invoice_to_db
from app.utils.money import money


@pytest.fixture(autouse=True)
def _login(monkeypatch, user):
    """save_invoice_to_db reads current_user.platform_mode; stand in our user."""
    monkeypatch.setattr(upload_module, 'current_user', user)


def _vme110_invoice():
    # VME110, qty 2, line cost 102.09. Per-unit profit 25.52 x 2 = 51.04, which
    # drifts from the line profit (51.05) — so a per-unit-times-qty total would
    # NOT reconcile, but the line-authority total does.
    return {
        'supplier': 'YESSS',
        'invoice_number': 'INV-VME110',
        'total_ex_tax': 102.09,
        'items': [{
            'part_number': 'VME110', 'description': 'VME110',
            'quantity': 2, 'total_amount': 102.09,
            'cost_per_item': 51.05, 'selling_price': 76.57,
            'calculated_selling_price': 76.57, 'qb_selling_price': None,
            'markup_percent': 50, 'profit_per_item': 25.52,
            'original_unit_price': 0, 'discount': '44',
        }],
    }


def test_vme110_totals_reconcile(app, user):
    inv = save_invoice_to_db(_vme110_invoice(), 'vme110.pdf', user.id)
    # The headline invariant: profit == selling - cost, to the penny.
    assert money(inv.total_profit) == money(inv.total_selling) - money(inv.total_cost)
    assert money(inv.total_cost) == Decimal('102.09')
    assert money(inv.total_selling) == Decimal('153.14')   # money(76.57 * 2)
    assert money(inv.total_profit) == Decimal('51.05')      # 153.14 - 102.09 (not 25.52*2)
