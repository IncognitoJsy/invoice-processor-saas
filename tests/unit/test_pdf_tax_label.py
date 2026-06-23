"""
Tests for the invoice/quote PDF tax line (pdf_generator._tax_label / _fmt_rate).

The tax line shows the user's PICKED output tax-code name + the document's snapshot rate +
the tax amount (in the adjacent column), e.g. 'GST (5%)' | '£5.00'. The code name falls back
to the generic tax_type, then to 'Tax', when no pick is stored.
"""
import types
from decimal import Decimal

from app.services import pdf_generator as P


def test_fmt_rate_strips_trailing_zeros():
    assert P._fmt_rate(Decimal('5.00')) == '5'
    assert P._fmt_rate(Decimal('17.50')) == '17.5'
    assert P._fmt_rate(Decimal('20.00')) == '20'
    assert P._fmt_rate(Decimal('5')) == '5'


def test_tax_label_uses_picked_code_name():
    inv = types.SimpleNamespace(tax_rate=Decimal('5.00'))
    user = types.SimpleNamespace(output_tax_code_name='GST', tax_type='GST')
    assert P._tax_label(inv, user) == 'GST (5%)'


def test_tax_label_falls_back_to_tax_type_then_tax():
    inv = types.SimpleNamespace(tax_rate=Decimal('20.00'))
    # No pick -> generic tax_type.
    assert P._tax_label(inv, types.SimpleNamespace(output_tax_code_name=None, tax_type='VAT')) == 'VAT (20%)'
    # Nothing at all -> 'Tax'.
    assert P._tax_label(inv, types.SimpleNamespace()) == 'Tax (20%)'


def test_totals_block_renders_with_tax_line():
    from reportlab.lib.colors import HexColor
    inv = types.SimpleNamespace(subtotal=Decimal('100.00'), tax_rate=Decimal('5.00'),
                                tax_amount=Decimal('5.00'), total=Decimal('105.00'))
    user = types.SimpleNamespace(output_tax_code_name='GST', tax_type='GST')
    # Smoke: builds the totals Table (with the enriched tax label) without raising.
    table = P._totals_block(inv, user, HexColor('#2563eb'))
    assert table is not None
