"""Sync-mode customer resolution for Jobs: find-or-create a local Customer for a picked QBO/Xero
customer, keyed on (user_id, source, external_id).

Critical properties (a mislinked customer on a job would corrupt job cost history):
  * a Parent:Child sub-customer resolves to ONE local Customer,
  * that link is STABLE across a rename in the accounting software (same row, name refreshed),
  * repeat selection never creates a duplicate,
  * the full-suite jobs flow (local customer_id) is unchanged.
"""
from app.models.user import User
from app.models.customer import Customer
from app.models.user_preference import CustomerCache
from app.models.quickbooks import QuickBooksConnection
from app.models.job_card import JobCard
from app.services.customer_link import resolve_local_customer, user_sync_source

_HTTPS = {'X-Forwarded-Proto': 'https'}
_n = [0]


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)


def _user(db, mode='sync'):
    _n[0] += 1
    u = User(email=f'{mode}-{_n[0]}@ex.com', password_hash='x', platform_mode=mode,
             subscription_plan='pro', subscription_status='active')
    db.session.add(u); db.session.commit()
    return u


def _qb_conn(db, user):
    c = QuickBooksConnection(user_id=user.id, realm_id='r', access_token='a', refresh_token='r',
                             is_active=True)
    db.session.add(c); db.session.commit()
    return c


def _cache_row(db, user, external_id, display, fqn=None, source='quickbooks'):
    row = CustomerCache(user_id=user.id, source=source, external_id=external_id,
                        display_name=display, fully_qualified_name=fqn)
    db.session.add(row); db.session.commit()
    return row


# ── Sub-customer resolves to ONE local customer, stable across a rename ──────────────────────
def test_subcustomer_resolves_once_and_survives_rename(app, db):
    u = _user(db, 'sync')
    _cache_row(db, u, '2002', 'Handois Lodge', 'Pierre Genee Builders Ltd:Handois Lodge')

    c1 = resolve_local_customer(u.id, 'quickbooks', '2002')
    db.session.commit()
    assert c1.name == 'Pierre Genee Builders Ltd:Handois Lodge'   # FQN preserved for sub-customer
    assert c1.external_id == '2002' and c1.source == 'quickbooks'
    assert Customer.query.filter_by(user_id=u.id).count() == 1

    # Repeat selection → SAME row, no duplicate.
    c2 = resolve_local_customer(u.id, 'quickbooks', '2002')
    db.session.commit()
    assert c2.id == c1.id
    assert Customer.query.filter_by(user_id=u.id).count() == 1

    # Rename in QBO (cache updated) → same local row, name refreshed, still no duplicate.
    row = CustomerCache.query.filter_by(user_id=u.id, external_id='2002').first()
    row.fully_qualified_name = 'Pierre Genee Builders Ltd:Handois Lodge (Plot 2)'
    db.session.commit()
    c3 = resolve_local_customer(u.id, 'quickbooks', '2002')
    db.session.commit()
    assert c3.id == c1.id
    assert c3.name == 'Pierre Genee Builders Ltd:Handois Lodge (Plot 2)'
    assert Customer.query.filter_by(user_id=u.id).count() == 1


def test_two_subcustomers_same_parent_are_distinct_rows(app, db):
    u = _user(db, 'sync')
    _cache_row(db, u, '2002', 'Handois Lodge', 'Pierre Genee Builders Ltd:Handois Lodge')
    _cache_row(db, u, '2003', 'Plot 5', 'Pierre Genee Builders Ltd:Plot 5')
    a = resolve_local_customer(u.id, 'quickbooks', '2002')
    b = resolve_local_customer(u.id, 'quickbooks', '2003')
    db.session.commit()
    assert a.id != b.id
    assert Customer.query.filter_by(user_id=u.id).count() == 2


def test_cache_miss_uses_fallback_then_none(app, db):
    u = _user(db, 'sync')
    assert resolve_local_customer(u.id, 'quickbooks', '9999') is None      # no cache, no fallback
    c = resolve_local_customer(u.id, 'quickbooks', '9999', fallback_name='Typed Name')
    db.session.commit()
    assert c is not None and c.name == 'Typed Name' and c.external_id == '9999'


def test_provider_detection(app, db):
    u = _user(db, 'sync')
    assert user_sync_source(u) is None
    _qb_conn(db, u)
    assert user_sync_source(u) == 'quickbooks'


# ── Route: sync create materialises the local customer; full create is unchanged ────────────
def test_sync_create_job_materialises_customer(app, db):
    u = _user(db, 'sync'); _qb_conn(db, u)
    _cache_row(db, u, '2002', 'Handois Lodge', 'Pierre Genee Builders Ltd:Handois Lodge')
    client = app.test_client(); _login(client, u.id)
    r = client.post('/jobs/create', json={'name': 'Rewire', 'external_customer_id': '2002'},
                    headers=_HTTPS)
    assert r.status_code == 200 and r.get_json()['success'] is True
    cust = Customer.query.filter_by(user_id=u.id, external_id='2002').first()
    assert cust is not None
    job = JobCard.query.get(r.get_json()['job_id'])
    assert job.customer_id == cust.id
    assert job.customer.name == 'Pierre Genee Builders Ltd:Handois Lodge'


def test_full_create_job_uses_local_customer_unchanged(app, db):
    u = _user(db, 'full')
    c = Customer(user_id=u.id, name='Local Co')       # full-suite native customer (no external id)
    db.session.add(c); db.session.commit()
    client = app.test_client(); _login(client, u.id)
    r = client.post('/jobs/create', json={'name': 'Job', 'customer_id': c.id}, headers=_HTTPS)
    assert r.status_code == 200 and r.get_json()['success'] is True
    job = JobCard.query.get(r.get_json()['job_id'])
    assert job.customer_id == c.id
    assert c.external_id is None and c.source is None  # untouched; no materialisation
    assert Customer.query.filter_by(user_id=u.id).count() == 1
