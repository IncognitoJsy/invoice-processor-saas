"""Render smoke tests for the shared CustomerPicker wiring — catch Jinja/template breakage from the
invoice-picker extraction and the jobs dropdown (there is otherwise no test that renders these pages).
"""
from app.models.user import User
from app.models.customer import Customer
from app.models.quickbooks import QuickBooksConnection

_HTTPS = {'X-Forwarded-Proto': 'https'}
_n = [0]


def _login(client, uid):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)


def _user(db, mode='sync'):
    _n[0] += 1
    u = User(email=f'r-{_n[0]}@ex.com', password_hash='x', platform_mode=mode,
             subscription_plan='pro', subscription_status='active')
    db.session.add(u); db.session.commit()
    return u


def _qb(db, user):
    db.session.add(QuickBooksConnection(user_id=user.id, realm_id='r', access_token='a',
                                        refresh_token='r', is_active=True))
    db.session.commit()


def test_invoices_page_renders_with_shared_picker(app, db):
    u = _user(db, 'sync'); _qb(db, u)
    client = app.test_client(); _login(client, u.id)
    r = client.get('/invoices', headers=_HTTPS)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'js/customer_picker.js' in html            # shared component included
    assert 'id="qb-customer-picker"' in html          # QB container present
    assert 'id="xero-customer-picker"' in html        # Xero container present
    assert 'data-cp="search"' in html and 'data-cp="hidden"' in html
    assert 'id="qb-customer-select"' in html          # hidden id preserved (syncToQuickBooks unchanged)


def test_jobs_page_renders_picker_when_connected(app, db):
    u = _user(db, 'sync'); _qb(db, u)
    client = app.test_client(); _login(client, u.id)
    r = client.get('/jobs/', headers=_HTTPS)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'js/customer_picker.js' in html
    assert 'id="new-job-customer-picker"' in html
    assert "provider: 'quickbooks'" in html           # instantiated for the connected provider


def test_jobs_full_mode_renders_local_select(app, db):
    u = _user(db, 'full')
    c = Customer(user_id=u.id, name='Local Co'); db.session.add(c); db.session.commit()
    client = app.test_client(); _login(client, u.id)
    r = client.get('/jobs/', headers=_HTTPS)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="new-job-customer"' in html            # local <select>, not the cache picker
    assert 'Local Co' in html
