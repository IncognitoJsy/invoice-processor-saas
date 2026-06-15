"""Tenant-isolation tests for labour logging (AUDIT risk #6).

/employees/labour/log accepted any job_card_id / customer_id by primary key,
so one tenant could link labour against another tenant's job card or customer.
These tests prove a cross-tenant id is now rejected (404) with no row written,
while a tenant's own ids still work.
"""
from app.models.user import User
from app.models.customer import Customer
from app.models.job_card import JobCard
from app.models.employee import Employee, LabourEntry

# HTTPS is enforced; present forwarded-proto to avoid a 301 (same idiom as the
# other integration tests).
_HTTPS = {'X-Forwarded-Proto': 'https'}


def _tenant(db, email):
    """A full-mode user with a customer + job card + employee of their own."""
    # Full platform mode (require_full_mode) + an active paid plan so the
    # subscription wall (app.before_request) lets the request through.
    u = User(email=email, password_hash='x', platform_mode='full',
             subscription_plan='pro', subscription_status='active')
    db.session.add(u)
    db.session.commit()
    cust = Customer(user_id=u.id, name=f'{email} customer')
    emp = Employee(user_id=u.id, name=f'{email} worker', pay_rate=20, charge_out_rate=40)
    db.session.add_all([cust, emp])
    db.session.commit()
    job = JobCard(user_id=u.id, customer_id=cust.id, name=f'{email} job')
    db.session.add(job)
    db.session.commit()
    return {'user': u, 'customer': cust, 'employee': emp, 'job': job}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def test_cannot_log_labour_against_another_tenants_job_card(app, db):
    """The core assertion: foreign job_card_id → 404, no entry written."""
    victim = _tenant(db, 'victim@x')
    attacker = _tenant(db, 'attacker@x')

    client = app.test_client()
    _login(client, attacker['user'])
    resp = client.post('/employees/labour/log', headers=_HTTPS, json={
        'employee_id': attacker['employee'].id,
        'job_card_id': victim['job'].id,   # not the attacker's
        'hours': 2,
    })

    assert resp.status_code == 404
    assert LabourEntry.query.count() == 0


def test_cannot_log_labour_against_another_tenants_customer(app, db):
    """Same IDOR class via a directly-supplied customer_id → 404, no entry."""
    victim = _tenant(db, 'victim@x')
    attacker = _tenant(db, 'attacker@x')

    client = app.test_client()
    _login(client, attacker['user'])
    resp = client.post('/employees/labour/log', headers=_HTTPS, json={
        'employee_id': attacker['employee'].id,
        'customer_id': victim['customer'].id,   # not the attacker's
        'hours': 2,
    })

    assert resp.status_code == 404
    assert LabourEntry.query.count() == 0


def test_can_log_labour_against_own_job_card(app, db):
    """Positive control: own job card works and derives the right customer."""
    tenant = _tenant(db, 'tenant@x')

    client = app.test_client()
    _login(client, tenant['user'])
    resp = client.post('/employees/labour/log', headers=_HTTPS, json={
        'employee_id': tenant['employee'].id,
        'job_card_id': tenant['job'].id,
        'hours': 2,
    })

    assert resp.status_code == 200
    entries = LabourEntry.query.all()
    assert len(entries) == 1
    assert entries[0].job_card_id == tenant['job'].id
    assert entries[0].customer_id == tenant['customer'].id
    assert entries[0].user_id == tenant['user'].id
