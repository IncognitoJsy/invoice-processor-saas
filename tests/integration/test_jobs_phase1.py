"""Phase 1 Jobs: sync-mode de-gate, job metadata, and the completion snapshot.

Covers the four named acceptance tests:
  * snapshot immune to a later pay-rate change (and to labour-row edits),
  * re-open preserves prior snapshot(s) + re-complete writes a new version (latest wins),
  * sync-mode attach sets Invoice.job_card_id with NO CustomerInvoice,
  * full-mode attach is unchanged (still builds the CustomerInvoice draft).
Plus: materials figures (mode-agnostic selling×qty), metadata round-trip, and the ENABLE_JOBS gate.

Note: the `app` fixture keeps an app_context open for the whole test, so tests use the `db` fixture
directly (no nested app.app_context(), which would detach instances).
"""
from decimal import Decimal

from app.models.user import User
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.models.employee import Employee, LabourEntry
from app.models.job_card import JobCard
from app.services.job_financials import compute_job_financials

_HTTPS = {'X-Forwarded-Proto': 'https'}
_counter = [0]


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)


def _user(db, mode='sync'):
    _counter[0] += 1
    u = User(email=f'{mode}-{_counter[0]}@example.com', password_hash='x', platform_mode=mode,
             subscription_plan='pro', subscription_status='active',
             invoice_prefix='INV', next_invoice_number=1, default_payment_terms='30')
    db.session.add(u); db.session.commit()
    return u


def _customer(db, user, name='Acme'):
    c = Customer(user_id=user.id, name=name)
    db.session.add(c); db.session.commit()
    return c


def _job(db, user, customer, **kw):
    j = JobCard(user_id=user.id, customer_id=customer.id, name=kw.pop('name', 'Job'),
                status=kw.pop('status', 'in_progress'), **kw)
    db.session.add(j); db.session.commit()
    return j


def _invoice_with_items(db, user, items, job=None):
    _counter[0] += 1
    inv = Invoice(user_id=user.id, supplier_name='YESSS Electrical', status='completed',
                  invoice_number=f'S-{_counter[0]}', total_cost=Decimal('0'),
                  job_card_id=(job.id if job else None))
    db.session.add(inv); db.session.flush()
    for it in items:
        db.session.add(InvoiceItem(
            invoice_id=inv.id, part_number=it.get('pn', 'P'), quantity=Decimal(str(it['qty'])),
            cost_per_item=Decimal(str(it.get('cost', it['total']))), total_amount=Decimal(str(it['total'])),
            selling_price=Decimal(str(it['sell'])), excluded=it.get('excluded', False)))
    db.session.commit()
    return inv


def _employee(db, user, pay, charge):
    e = Employee(user_id=user.id, name='Sparky', pay_rate=Decimal(str(pay)),
                 charge_out_rate=Decimal(str(charge)))
    db.session.add(e); db.session.commit()
    return e


def _labour(db, user, job, emp, hours, pay=None, charge=None, contrib='6.5'):
    le = LabourEntry(user_id=user.id, employee_id=emp.id, job_card_id=job.id,
                     hours=Decimal(str(hours)),
                     pay_rate=Decimal(str(pay if pay is not None else emp.pay_rate)),
                     charge_out_rate=Decimal(str(charge if charge is not None else emp.charge_out_rate)),
                     employer_contribution_rate=Decimal(contrib), status='logged')
    db.session.add(le); db.session.commit()
    return le


# ── Materials: mode-agnostic selling×qty, excluded lines ignored ────────────────────────────
def test_materials_financials(app, db):
    u = _user(db); c = _customer(db, u); job = _job(db, u, c)
    _invoice_with_items(db, u, [
        {'qty': 2, 'sell': 10.00, 'total': 12.00},
        {'qty': 3, 'sell': 5.00, 'total': 9.00},
        {'qty': 1, 'sell': 100.00, 'total': 50.00, 'excluded': True},  # ignored
    ], job=job)
    fin = compute_job_financials(job)
    assert fin['materials_cost'] == Decimal('21.00')
    assert fin['materials_sold'] == Decimal('35.00')          # 2×10 + 3×5, excluded dropped
    assert fin['materials_profit'] == Decimal('14.00')


# ── De-gate: sync user reaches /jobs; ENABLE_JOBS off → hidden ──────────────────────────────
def test_sync_user_can_reach_jobs(app, db):
    u = _user(db, 'sync')
    client = app.test_client(); _login(client, u.id)
    assert client.get('/jobs/', headers=_HTTPS).status_code == 200


def test_enable_jobs_flag_off_hides_jobs(app, db):
    u = _user(db, 'sync')
    app.config['ENABLE_JOBS'] = False
    try:
        client = app.test_client(); _login(client, u.id)
        assert client.get('/jobs/', headers=_HTTPS).status_code == 404
    finally:
        app.config['ENABLE_JOBS'] = True


# ── Attach: sync sets FK only; full unchanged (builds CustomerInvoice) ───────────────────────
def test_sync_attach_sets_fk_no_customer_invoice(app, db):
    from app.models.customer_invoice import CustomerInvoice
    u = _user(db, 'sync'); c = _customer(db, u); job = _job(db, u, c)
    inv = _invoice_with_items(db, u, [{'qty': 1, 'sell': 10, 'total': 8}])
    job_id, inv_id = job.id, inv.id
    client = app.test_client(); _login(client, u.id)
    r = client.post('/jobs/api/attach-supplier-invoice', json={'invoice_id': inv_id, 'job_id': job_id},
                    headers=_HTTPS)
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] is True
    assert body['customer_invoice_id'] is None            # NO CustomerInvoice for sync
    assert Invoice.query.get(inv_id).job_card_id == job_id   # FK set
    assert CustomerInvoice.query.count() == 0                 # nothing created


def test_full_attach_still_builds_customer_invoice(app, db):
    from app.models.customer_invoice import CustomerInvoice
    u = _user(db, 'full'); c = _customer(db, u); job = _job(db, u, c)
    inv = _invoice_with_items(db, u, [{'qty': 2, 'sell': 10, 'total': 8, 'pn': 'X'}])
    job_id, inv_id = job.id, inv.id
    client = app.test_client(); _login(client, u.id)
    r = client.post('/jobs/api/attach-supplier-invoice',
                    json={'invoice_id': inv_id, 'job_id': job_id, 'invoice_mode': 'itemised'},
                    headers=_HTTPS)
    assert r.status_code == 200
    body = r.get_json()
    assert body['success'] is True
    assert body['customer_invoice_id'] is not None        # full-suite path unchanged
    assert Invoice.query.get(inv_id).job_card_id == job_id
    assert CustomerInvoice.query.filter_by(job_card_id=job_id).count() == 1


# ── Metadata round-trips (incl. JSONB room_types) ───────────────────────────────────────────
def test_metadata_roundtrip(app, db):
    u = _user(db); c = _customer(db, u)
    job = _job(db, u, c, job_type='rewire_full', room_count=6,
               room_types=['kitchen', 'bathroom'], floor_area_sqm=Decimal('85.50'),
               floor_area_unit_pref='sqft')
    jid = job.id
    db.session.expire_all()
    got = JobCard.query.get(jid)
    assert got.job_type == 'rewire_full'
    assert got.job_type_label == 'Full rewire'
    assert got.room_types == ['kitchen', 'bathroom']
    assert got.room_count == 6
    assert got.floor_area_sqm == Decimal('85.50')


# ── Snapshot on complete + immune to a later pay-rate change / labour edit ───────────────────
def test_snapshot_freezes_and_is_immune_to_pay_rate_change(app, db):
    u = _user(db); c = _customer(db, u); job = _job(db, u, c)
    _invoice_with_items(db, u, [{'qty': 2, 'sell': 10, 'total': 12}], job=job)
    emp = _employee(db, u, pay=20, charge=40)
    _labour(db, u, job, emp, hours=10)   # cost 10×20×1.065=213.00, charged 400.00
    jid, uid = job.id, u.id
    client = app.test_client(); _login(client, uid)
    assert client.post(f'/jobs/{jid}/update-status', json={'status': 'complete'},
                       headers=_HTTPS).status_code == 200

    snap = JobCard.query.get(jid).latest_snapshot
    assert snap.snapshot_version == 1
    assert snap.materials_sold == Decimal('20.00')      # 2×10
    assert snap.labour_cost == Decimal('213.00')
    assert snap.labour_charged == Decimal('400.00')
    assert snap.labour_profit == Decimal('187.00')
    assert snap.overall_profit == Decimal('195.00')     # (20-12) materials + 187 labour − 0 direct
    assert snap.direct_costs_total == Decimal('0.00')
    assert snap.labour_breakdown[0]['pay_rate'] == 20.0

    # Pay rise AFTER completion — bump both the employee AND the existing labour row.
    Employee.query.filter_by(user_id=uid).first().pay_rate = Decimal('30')
    LabourEntry.query.filter_by(job_card_id=jid).first().pay_rate = Decimal('30')
    db.session.commit()

    # Frozen snapshot is UNCHANGED; a fresh live compute would now differ.
    assert JobCard.query.get(jid).latest_snapshot.labour_cost == Decimal('213.00')
    assert compute_job_financials(JobCard.query.get(jid))['labour_cost'] == Decimal('319.50')  # 10×30×1.065


# ── Re-open preserves prior snapshot; re-complete writes a new version (latest wins) ─────────
def test_reopen_preserves_and_recomplete_versions(app, db):
    u = _user(db); c = _customer(db, u); job = _job(db, u, c)
    emp = _employee(db, u, pay=20, charge=40)
    _labour(db, u, job, emp, hours=5)    # v1 labour: 5×40 = 200 charged
    jid, uid = job.id, u.id
    client = app.test_client(); _login(client, uid)

    # Complete → v1
    client.post(f'/jobs/{jid}/update-status', json={'status': 'complete'}, headers=_HTTPS)
    job = JobCard.query.get(jid)
    assert job.snapshots.count() == 1
    v1_labour = job.latest_snapshot.labour_charged        # 200.00

    # Re-open (snapshot preserved) then add more labour
    client.post(f'/jobs/{jid}/update-status', json={'status': 'in_progress'}, headers=_HTTPS)
    job = JobCard.query.get(jid)
    assert job.snapshots.count() == 1                     # nothing lost on re-open
    _labour(db, u, job, emp, hours=5)                     # more work (total now 10h)

    # Re-complete → v2
    client.post(f'/jobs/{jid}/update-status', json={'status': 'complete'}, headers=_HTTPS)
    job = JobCard.query.get(jid)
    versions = sorted(s.snapshot_version for s in job.snapshots.all())
    assert versions == [1, 2]                             # prior preserved, new version added
    assert job.latest_snapshot.snapshot_version == 2      # latest wins
    v1 = job.snapshots.filter_by(snapshot_version=1).first()
    assert v1.labour_charged == v1_labour                 # v1 unchanged (200)
    assert job.latest_snapshot.labour_charged == Decimal('400.00')  # 10×40 across both entries
