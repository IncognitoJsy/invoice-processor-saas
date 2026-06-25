"""Phase 2: the manual price-override route works on QUOTE lines (Invoice document_type='quote'),
since quote lines are InvoiceItem rows. Pins the assumption the quotes-view override rests on:
PUT /invoices/item/<id>/price overrides a quote line, recomputes its markup/profit, and recalcs
the quote's selling/profit totals; ?reset=true reverts to the calculated price. Frontend Phase 2
adds no backend — this is the existing route exercised against a quote.
"""
import pytest

from app.models.invoice import Invoice, InvoiceItem


def _make_quote(db, user):
    q = Invoice(user_id=user.id, document_type='quote', supplier_name='Wholesale Electrics',
                invoice_number='QO-OVR-1', total_cost=50, total_selling=60, total_profit=10,
                status='completed')
    db.session.add(q)
    db.session.flush()
    i1 = InvoiceItem(invoice_id=q.id, part_number='A', quantity=2, cost_per_item=10,
                     total_amount=20, selling_price=12, calculated_selling_price=12,
                     markup_percent=20, profit_per_item=2, price_overridden=False)
    i2 = InvoiceItem(invoice_id=q.id, part_number='B', quantity=1, cost_per_item=30,
                     total_amount=30, selling_price=36, calculated_selling_price=36,
                     markup_percent=20, profit_per_item=6, price_overridden=False)
    db.session.add_all([i1, i2])
    db.session.commit()
    return q.id, i1.id, i2.id


def _client(app, user, db):
    user.subscription_plan = 'full-starter'
    user.subscription_status = 'active'
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return c


def test_override_on_quote_line_recalcs_quote_totals(app, user, db):
    qid, i1, i2 = _make_quote(db, user)
    c = _client(app, user, db)
    r = c.put(f'/invoices/item/{i1}/price', json={'selling_price': 20},
              headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200 and r.get_json()['success'] is True

    db.session.expire_all()
    line = InvoiceItem.query.get(i1)
    quote = Invoice.query.get(qid)
    assert line.price_overridden is True
    assert float(line.selling_price) == 20.0
    assert float(line.markup_percent) == 100.0       # (20-10)/10*100
    assert float(line.profit_per_item) == 10.0
    # quote totals recalced: selling = 2*20 + 1*36 = 76 ; profit = 2*10 + 1*6 = 26
    assert float(quote.total_selling) == 76.0
    assert float(quote.total_profit) == 26.0


def test_reset_reverts_quote_line_to_calculated(app, user, db):
    qid, i1, i2 = _make_quote(db, user)
    c = _client(app, user, db)
    c.put(f'/invoices/item/{i1}/price', json={'selling_price': 20},
          headers={'X-Forwarded-Proto': 'https'})
    r = c.put(f'/invoices/item/{i1}/price?reset=true', headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200

    db.session.expire_all()
    line = InvoiceItem.query.get(i1)
    quote = Invoice.query.get(qid)
    assert line.price_overridden is False
    assert float(line.selling_price) == 12.0          # reverted to calculated_selling_price
    assert float(quote.total_selling) == 60.0         # back to 2*12 + 36


def test_override_tenant_isolated_on_quotes(app, user, db):
    """A second user cannot override another tenant's quote line."""
    from app.models.user import User
    qid, i1, i2 = _make_quote(db, user)
    other = User(email='other-q@example.com', password_hash='x', platform_mode='sync',
                 subscription_plan='full-starter', subscription_status='active')
    db.session.add(other)
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['_user_id'] = str(other.id)
    r = c.put(f'/invoices/item/{i1}/price', json={'selling_price': 99},
              headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 403
    db.session.expire_all()
    assert InvoiceItem.query.get(i1).price_overridden is False  # untouched
