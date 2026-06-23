"""
generate_quote_pdf renders a quote through the shared invoice templates via the _QuoteDoc
adapter (so it inherits the output-tax label and money formatting), with the quote's own
quote_number / expiry_date and no payment-terms label.
"""
import io
import types
from datetime import date
from decimal import Decimal

from pdfminer.high_level import extract_text

from app.services.pdf_generator import generate_quote_pdf, generate_invoice_pdf, _QuoteDoc


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


def _fake_invoice():
    cust = types.SimpleNamespace(display_name='Acme Ltd', email='a@b.com',
                                 full_address='1 St, Jersey')
    line = types.SimpleNamespace(description='Cable', quantity=Decimal('2'),
                                 unit_price=Decimal('10.0000'), line_total=Decimal('20.00'))
    return types.SimpleNamespace(
        invoice_number='INV-9', due_date=date(2026, 7, 1), issue_date=date(2026, 6, 1),
        payment_terms_label='Net 30',
        subtotal=Decimal('20.00'), tax_rate=Decimal('5.00'), tax_amount=Decimal('1.00'),
        total=Decimal('21.00'), notes='', customer=cust, lines=[line], payment_terms='30')


def test_quote_pdf_uses_quote_wording_not_invoice():
    # Real rendered PDF text: a quote must read 'QUOTE'/'TOTAL'/'Valid Until' and must NOT
    # carry invoice wording ('INVOICE', 'TOTAL DUE', 'Due Date').
    text = extract_text(io.BytesIO(generate_quote_pdf(_fake_quote(), _fake_user()))).upper()
    assert 'QUOTE' in text
    assert 'VALID UNTIL' in text
    assert 'TOTAL' in text
    assert 'INVOICE' not in text
    assert 'TOTAL DUE' not in text
    assert 'DUE DATE' not in text


def test_invoice_pdf_wording_unchanged():
    # The shared default labels still render invoice wording for invoices (regression guard).
    text = extract_text(io.BytesIO(generate_invoice_pdf(_fake_invoice(), _fake_user()))).upper()
    assert 'INVOICE' in text
    assert 'TOTAL DUE' in text
    assert 'DUE DATE' in text


def _bank_user(template='classic'):
    u = _fake_user(template)
    u.bank_name = 'Jersey Bank'
    u.bank_account_name = 'Me Ltd'
    u.bank_account_number = '12345678'
    u.bank_sort_code = '00-00-00'
    u.bank_iban = None
    return u


def test_quote_pdf_omits_payment_reference_even_with_bank_details():
    # With bank details set, the PAYMENT DETAILS block renders — but a quote must NOT print the
    # "use <number> as your payment reference" / "Reference: <number>" line (you don't pay a quote).
    for tmpl in ('classic', 'branded'):
        text = extract_text(io.BytesIO(generate_quote_pdf(_fake_quote(), _bank_user(tmpl)))).upper()
        assert 'PAYMENT DETAILS' in text, tmpl     # bank block did render
        assert 'REFERENCE' not in text, tmpl       # but no payment-reference line


def test_invoice_pdf_keeps_payment_reference():
    for tmpl in ('classic', 'branded'):
        text = extract_text(io.BytesIO(generate_invoice_pdf(_fake_invoice(), _bank_user(tmpl)))).upper()
        assert 'PAYMENT DETAILS' in text, tmpl
        assert 'REFERENCE' in text, tmpl           # invoice still shows the payment reference
