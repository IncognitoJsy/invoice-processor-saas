"""Job-side attach/detach/move of processed supplier invoices — the retrospective, sync-independent
link. Proves the double-entry safety the feature depends on:
  * attaching an already-SYNCED invoice writes ONLY job_card_id — qb/xero sync state is untouched
    (no re-push path exists on this route),
  * detach clears the link, move overwrites it, attach is idempotent,
  * synced AND unsynced invoices are both attachable (never restricted by status),
and the picker surfaces sync status + current job.
"""
from datetime import datetime
from decimal import Decimal

from app.models.user import User
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.job_card import JobCard

_HTTPS = {'X-Forwarded-Proto': 'https'}
_n = [0]


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)


def _user(db, mode='sync'):
    _n[0] += 1
    u = User(email=f'a-{_n[0]}@ex.com', password_hash='x', platform_mode=mode,
             subscription_plan='pro', subscription_status='active')
    db.session.add(u); db.session.commit()
    return u


def _job(db, user, name='Job'):
    c = Customer(user_id=user.id, name=f'C{_n[0]}'); db.session.add(c); db.session.commit()
    j = JobCard(user_id=user.id, customer_id=c.id, name=name, status='in_progress')
    db.session.add(j); db.session.commit()
    return j


def _invoice(db, user, synced=False, num='INV-1'):
    inv = Invoice(user_id=user.id, supplier_name='YESSS Electrical', status='completed',
                  invoice_number=num, total_cost=Decimal('100'),
                  qb_synced_at=(datetime.utcnow() if synced else None))
    db.session.add(inv); db.session.commit()
    return inv


# ── Attaching a SYNCED invoice touches ONLY the link, never the sync state ───────────────────
def test_attach_synced_invoice_sets_fk_only(app, db):
    u = _user(db, 'sync'); job = _job(db, u); inv = _invoice(db, u, synced=True)
    synced_before = inv.qb_synced_at
    client = app.test_client(); _login(client, u.id)
    r = client.post(f'/jobs/{job.id}/attach-invoice', json={'invoice_id': inv.id}, headers=_HTTPS)
    assert r.status_code == 200 and r.get_json()['success'] is True
    inv = Invoice.query.get(inv.id)
    assert inv.job_card_id == job.id          # link set
    assert inv.qb_synced_at == synced_before  # sync state UNTOUCHED — no re-push, no re-stamp


def test_attach_is_idempotent(app, db):
    u = _user(db, 'sync'); job = _job(db, u); inv = _invoice(db, u)
    client = app.test_client(); _login(client, u.id)
    for _ in range(2):
        client.post(f'/jobs/{job.id}/attach-invoice', json={'invoice_id': inv.id}, headers=_HTTPS)
    assert Invoice.query.get(inv.id).job_card_id == job.id
    # still a single scalar FK — nothing to duplicate
    assert Invoice.query.filter_by(job_card_id=job.id).count() == 1


def test_detach_and_move(app, db):
    u = _user(db, 'sync'); jobA = _job(db, u, 'A'); jobB = _job(db, u, 'B'); inv = _invoice(db, u)
    client = app.test_client(); _login(client, u.id)
    client.post(f'/jobs/{jobA.id}/attach-invoice', json={'invoice_id': inv.id}, headers=_HTTPS)
    assert Invoice.query.get(inv.id).job_card_id == jobA.id
    # Move: attach to B overwrites the FK (no duplicate, no second link)
    client.post(f'/jobs/{jobB.id}/attach-invoice', json={'invoice_id': inv.id}, headers=_HTTPS)
    assert Invoice.query.get(inv.id).job_card_id == jobB.id
    # Detach: clears the link
    r = client.post('/jobs/detach-invoice', json={'invoice_id': inv.id}, headers=_HTTPS)
    assert r.status_code == 200
    assert Invoice.query.get(inv.id).job_card_id is None


# ── Picker lists synced AND unsynced with status + current job (never restricts) ─────────────
def test_attachable_invoices_lists_status_and_current_job(app, db):
    u = _user(db, 'sync'); jobA = _job(db, u, 'A'); jobB = _job(db, u, 'B')
    unsynced = _invoice(db, u, synced=False, num='U-1')
    synced = _invoice(db, u, synced=True, num='S-1')
    client = app.test_client(); _login(client, u.id)
    # attach the synced one to jobB so it shows "on another job" when picking for jobA
    client.post(f'/jobs/{jobB.id}/attach-invoice', json={'invoice_id': synced.id}, headers=_HTTPS)

    r = client.get(f'/jobs/{jobA.id}/attachable-invoices', headers=_HTTPS)
    assert r.status_code == 200
    rows = {row['invoice_number']: row for row in r.get_json()['invoices']}
    assert rows['U-1']['synced'] is False and rows['S-1']['synced'] is True      # status shown
    assert rows['S-1']['current_job_id'] == jobB.id                               # move source visible
    assert rows['S-1']['current_job_name'] == 'B'
    assert rows['U-1']['current_job_id'] is None
    # both present — unsynced is NOT filtered out
    assert 'U-1' in rows and 'S-1' in rows


def test_job_view_and_invoice_modal_expose_attach_ui(app, db):
    from app.models.quickbooks import QuickBooksConnection
    u = _user(db, 'sync'); job = _job(db, u)
    db.session.add(QuickBooksConnection(user_id=u.id, realm_id='r', access_token='a',
                                        refresh_token='r', is_active=True)); db.session.commit()
    client = app.test_client(); _login(client, u.id)
    jv = client.get(f'/jobs/{job.id}', headers=_HTTPS).get_data(as_text=True)
    assert 'openAttachInvoiceModal()' in jv and 'id="attach-invoice-modal"' in jv   # job-side attach
    inv = client.get('/invoices', headers=_HTTPS).get_data(as_text=True)
    assert 'id="sync-job-attach-section"' in inv and 'loadSyncJobAttach' in inv      # invoice-side (sync)


def test_attachable_invoices_excludes_quotes(app, db):
    u = _user(db, 'sync'); job = _job(db, u)
    _invoice(db, u, num='REAL')
    quote = Invoice(user_id=u.id, supplier_name='x', status='completed', invoice_number='Q',
                    total_cost=Decimal('0'), document_type='quote')
    db.session.add(quote); db.session.commit()
    client = app.test_client(); _login(client, u.id)
    nums = [r['invoice_number'] for r in
            client.get(f'/jobs/{job.id}/attachable-invoices', headers=_HTTPS).get_json()['invoices']]
    assert 'REAL' in nums and 'Q' not in nums
