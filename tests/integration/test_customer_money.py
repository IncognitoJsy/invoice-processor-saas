"""Phase 2b — customer-document / report money is Decimal and reconciles.

Covers:
  * CustomerInvoice / CustomerQuote totals reconcile to the penny (incl. a line whose
    qty×unit needs half-up rounding and a tax that doesn't divide cleanly).
  * CustomerQuoteLine.calculate_total rounds HALF_UP (not banker's).
  * job_cards._recalculate_invoice rounds the tax (was float, never rounded).
  * The VAT-return endpoint (reports.api_vat) computes its boxes in Decimal.

(The printed-tax-vs-resolver reconciliation is Step 2c, not tested here.)
"""
from datetime import datetime
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
from app.models.customer_quote import CustomerQuote, CustomerQuoteLine
from app.models.invoice import Invoice
from app.web.job_cards import _recalculate_invoice
from app.utils.money import money

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _customer(db, user):
    c = Customer(user_id=user.id, name='Acme Ltd')
    db.session.add(c)
    db.session.flush()
    return c


# ── Customer invoice totals reconcile (qty that doesn't divide cleanly) ───────
def test_customer_invoice_totals_reconcile(app, db, user):
    cust = _customer(db, user)
    inv = CustomerInvoice(user_id=user.id, customer_id=cust.id, invoice_number='INV-1',
                          tax_rate=Decimal('5'))
    db.session.add(inv)
    db.session.flush()
    # line 1: 3 × 1.005 = 3.015 -> 3.02 ; line 2: 2 × 5.67 = 11.34
    for qty, unit in [(Decimal('3'), Decimal('1.005')), (Decimal('2'), Decimal('5.67'))]:
        db.session.add(CustomerInvoiceLine(
            customer_invoice_id=inv.id, description='x',
            quantity=qty, unit_price=unit, line_total=money(qty * unit)))
    db.session.flush()

    inv.recalculate_totals()

    assert inv.subtotal == Decimal('14.36')         # 3.02 + 11.34
    assert inv.tax_amount == Decimal('0.72')          # money(14.36 × 5%) = money(0.718)
    assert inv.total == Decimal('15.08')
    assert inv.total == inv.subtotal + inv.tax_amount  # reconciles to the penny


# ── Customer quote: line HALF_UP + totals reconcile ───────────────────────────
def test_customer_quote_line_half_up_and_reconcile(app, db, user):
    q = CustomerQuote(user_id=user.id, quote_number='Q-1', tax_rate=Decimal('5'))
    db.session.add(q)
    db.session.flush()
    # 1 × 2.005 = 2.005 -> HALF_UP 2.01 (banker's would give 2.00); 3 × 2.00 = 6.00
    l1 = CustomerQuoteLine(quote_id=q.id, description='a', quantity=Decimal('1'), unit_price=Decimal('2.005'))
    l2 = CustomerQuoteLine(quote_id=q.id, description='b', quantity=Decimal('3'), unit_price=Decimal('2.00'))
    db.session.add_all([l1, l2])
    db.session.flush()

    l1.calculate_total()
    l2.calculate_total()
    assert l1.line_total == Decimal('2.01')   # HALF_UP, not 2.00
    assert l2.line_total == Decimal('6.00')

    q.recalculate_totals()
    assert q.subtotal == Decimal('8.01')
    assert q.tax_amount == Decimal('0.40')      # money(8.01 × 5%) = money(0.4005)
    assert q.total == q.subtotal + q.tax_amount


# ── job_cards._recalculate_invoice rounds the tax (was float, never rounded) ──
def test_job_card_invoice_tax_is_rounded(app, db, user):
    cust = _customer(db, user)
    inv = CustomerInvoice(user_id=user.id, customer_id=cust.id, invoice_number='INV-JC',
                          tax_rate=Decimal('5'))
    db.session.add(inv)
    db.session.flush()
    db.session.add(CustomerInvoiceLine(
        customer_invoice_id=inv.id, description='materials',
        quantity=Decimal('1'), unit_price=Decimal('33.33'), line_total=Decimal('33.33')))
    db.session.flush()

    _recalculate_invoice(inv)

    assert inv.subtotal == Decimal('33.33')
    assert inv.tax_amount == Decimal('1.67')          # money(33.33 × 5%) = money(1.6665)
    assert inv.tax_amount.as_tuple().exponent == -2    # genuinely 2dp, not 1.66650000…
    assert inv.total == Decimal('35.00')
    assert inv.total == inv.subtotal + inv.tax_amount


# ── VAT-return boxes computed in Decimal (reports.api_vat) ────────────────────
def test_vat_return_boxes_are_decimal(app, db, user):
    user.tax_registered = True          # unified canonical flag (gates /api/vat)
    user.tax_rate = Decimal('20')       # canonical rate (box4 input-tax estimate)
    # Get past the subscription wall (minimal fixture user defaults to expired trial).
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    cust = _customer(db, user)
    when = datetime(2026, 6, 1, 12, 0)
    # two paid customer invoices -> output VAT 0.72 + 1.67 = 2.39, net 14.36 + 33.40 = 47.76
    for num, sub, tax, tot in [('CI-1', '14.36', '0.72', '15.08'), ('CI-2', '33.40', '1.67', '35.07')]:
        db.session.add(CustomerInvoice(
            user_id=user.id, customer_id=cust.id, invoice_number=num, status='paid',
            paid_at=when, subtotal=Decimal(sub), tax_amount=Decimal(tax), total=Decimal(tot),
            tax_rate=Decimal('5')))
    # one completed supplier invoice -> input net 33.33; box4 = money(33.33 × 20%) = 6.67
    db.session.add(Invoice(user_id=user.id, supplier_name='Supplier', status='completed',
                           processed_at=when, total_cost=Decimal('33.33')))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    resp = client.get('/reports/api/vat?date_from=2026-01-01&date_to=2026-12-31', headers=_HTTPS)
    assert resp.status_code == 200
    d = resp.get_json()
    assert d['box1_vat_due_sales'] == 2.39       # Σ output tax, penny-exact
    assert d['box6_total_sales_ex_vat'] == 47.76
    assert d['box4_vat_reclaimed'] == 6.67        # money(33.33 × 20%) — Decimal, not float
    assert d['box7_total_purchases_ex_vat'] == 33.33
    assert d['box5_net_vat_due'] == round(2.39 - 6.67, 2)
