"""
generate_quote_pdf renders a quote through the shared invoice templates via the _QuoteDoc
adapter (so it inherits the output-tax label and money formatting), with the quote's own
quote_number / expiry_date and no payment-terms label.
"""
import types
from datetime import date
from decimal import Decimal

from app.services.pdf_generator import generate_quote_pdf, _QuoteDoc


def _fake_quote():
    cust = types.SimpleNamespace(display_name='Acme Ltd', email='a@b.com',
                                 full_address='1 St, Jersey')
    line = types.SimpleNamespace(description='Cable', quantity=Decimal('2'),
                                 unit_price=Decimal('10.0000'), line_total=Decimal('20.00'))
    return types.SimpleNamespace(
        quote_number='Q-001', expiry_date=date(2026, 7, 1), issue_date=date(2026, 6, 1),
        subtotal=Decimal('20.00'), tax_rate=Decimal('5.00'), tax_amount=Decimal('1.00'),
        total=Decimal('21.00'), notes='', customer=cust, lines=[line], payment_terms='30')


def _fake_user(template='classic'):
    return types.SimpleNamespace(
        invoice_template=template, company_name='Me Ltd', trade_type='electrician',
        tax_registered=True, tax_number='GST123', tax_type='GST', output_tax_code_name='GST',
        invoice_colour=None, logo_url=None, invoice_notes=None,
        bank_name=None, bank_account_name=None, bank_account_number=None,
        bank_sort_code=None, bank_iban=None)


def test_quote_doc_adapter_maps_differing_fields():
    d = _QuoteDoc(_fake_quote())
    assert d.invoice_number == 'Q-001'              # quote_number
    assert d.due_date == date(2026, 7, 1)           # expiry_date
    assert d.payment_terms_label == ''              # quotes have no terms label
    assert d.subtotal == Decimal('20.00')           # everything else passes through


def test_generate_quote_pdf_renders_all_templates():
    quote = _fake_quote()
    for tmpl in ('classic', 'minimal', 'bold', 'professional', 'modern', 'branded'):
        pdf = generate_quote_pdf(quote, _fake_user(tmpl))
        assert pdf[:4] == b'%PDF', tmpl       # valid PDF, no ImportError/AttributeError
        assert len(pdf) > 1000, tmpl
