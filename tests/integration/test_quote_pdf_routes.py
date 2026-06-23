"""
Regression: the customer-quote PDF routes no longer 500 on a missing generate_quote_pdf.

Before the fix, `from app.services.pdf_generator import generate_quote_pdf` raised ImportError
inside both routes — GET /customer-quotes/<id>/pdf returned a raw 500, and POST
/customer-quotes/<id>/send returned {'error': "cannot import name 'generate_quote_pdf'…"}.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.customer_quote import CustomerQuote, CustomerQuoteLine

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _quote_with_line(db, user):
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    cust = Customer(user_id=user.id, name='Acme Ltd', email='acme@example.com')
    db.session.add(cust)
    db.session.flush()
    quote = CustomerQuote(user_id=user.id, customer_id=cust.id, quote_number='Q-1001',
                          status='draft', issue_date=date(2026, 6, 1),
                          expiry_date=date(2026, 7, 1), tax_rate=Decimal('5'))
    db.session.add(quote)
    db.session.flush()
    db.session.add(CustomerQuoteLine(quote_id=quote.id, description='Cable',
                                     quantity=Decimal('2'), unit_price=Decimal('10.00'),
                                     line_total=Decimal('20.00')))
    db.session.flush()
    quote.recalculate_totals()
    db.session.commit()
    return quote


def test_download_pdf_route_returns_pdf_not_500(app, db, user):
    quote = _quote_with_line(db, user)
    client = app.test_client()
    _login(client, user)
    resp = client.get(f'/customer-quotes/{quote.id}/pdf', headers=_HTTPS)
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.get_data()[:4] == b'%PDF'


def test_send_quote_route_no_longer_import_errors(app, db, user, monkeypatch):
    quote = _quote_with_line(db, user)
    # Stub the actual email send so we isolate the (previously broken) PDF import path.
    sent = {}
    def _fake_send(u, q, pdf, accept_url):
        sent['pdf'] = pdf
    monkeypatch.setattr('app.services.email_sender.send_quote_email', _fake_send)

    client = app.test_client()
    _login(client, user)
    resp = client.post(f'/customer-quotes/{quote.id}/send', headers=_HTTPS)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get('success') is True
    assert sent['pdf'][:4] == b'%PDF'   # a real PDF was generated and handed to the sender
