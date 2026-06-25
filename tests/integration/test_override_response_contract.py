"""Phase 5: the upload-result override is Alpine-native and patches the row from the route's JSON
response (Object.assign(item, d.item)) and relies on the response shape. Pin that contract:
PUT /invoices/item/<id>/price on an invoice line returns success + the updated InvoiceItem.to_dict()
(with price_overridden / selling_price / markup_percent) + invoice_totals — the exact fields the
Alpine patch reads. (The save/patch logic itself is client-side Alpine; this pins its server side.)
"""
import pytest

from app.models.invoice import Invoice, InvoiceItem


def _make_invoice(db, user):
    inv = Invoice(user_id=user.id, document_type='invoice', supplier_name='Wholesale Electrics',
                  invoice_number='UP-OVR-1', total_cost=50, total_selling=60, total_profit=10,
                  status='completed')
    db.session.add(inv)
    db.session.flush()
    i1 = InvoiceItem(invoice_id=inv.id, part_number='A', quantity=2, cost_per_item=10,
                     total_amount=20, selling_price=12, calculated_selling_price=12,
                     markup_percent=20, profit_per_item=2, price_overridden=False)
    db.session.add(i1)
    db.session.commit()
    return inv.id, i1.id


def _client(app, user, db):
    user.subscription_plan = 'full-starter'
    user.subscription_status = 'active'
    db.session.commit()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    return c


def test_override_response_contract_for_alpine_patch(app, user, db):
    _, i1 = _make_invoice(db, user)
    c = _client(app, user, db)
    r = c.put(f'/invoices/item/{i1}/price', json={'selling_price': 20},
              headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] is True
    # fields the Alpine Object.assign(item, d.item) reads
    item = body['item']
    assert item['price_overridden'] is True
    assert float(item['selling_price']) == 20.0
    assert float(item['markup_percent']) == 100.0
    assert float(item['profit_per_item']) == 10.0
    assert 'updated_at' in item and 'id' in item
    # invoice_totals block the response also carries
    assert float(body['invoice_totals']['total_selling']) == 2 * 20.0      # only line, qty 2
    assert float(body['invoice_totals']['total_profit']) == 2 * 10.0


def test_reset_response_contract(app, user, db):
    _, i1 = _make_invoice(db, user)
    c = _client(app, user, db)
    c.put(f'/invoices/item/{i1}/price', json={'selling_price': 20},
          headers={'X-Forwarded-Proto': 'https'})
    r = c.put(f'/invoices/item/{i1}/price?reset=true', headers={'X-Forwarded-Proto': 'https'})
    assert r.status_code == 200
    item = r.get_json()['item']
    assert item['price_overridden'] is False
    assert float(item['selling_price']) == 12.0   # reverted to calculated_selling_price
