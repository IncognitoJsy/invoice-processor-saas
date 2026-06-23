"""
Tests for the unify-on-tax_* change: the Settings tax-registration handler (settings.save_tax),
the picked-but-not-registered warning, the GST/VAT label (tax_noun), and the migrated
reports.py /api/vat gate (now keyed off tax_registered, not vat_registered).
"""
import types
from decimal import Decimal

import pytest

from app.models.user import User
from app.models.quickbooks import QuickBooksConnection
from app.utils.tax import tax_noun, picked_but_not_registered

_HTTPS = {'X-Forwarded-Proto': 'https'}


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _active_plan(db, user):
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    db.session.commit()


def _connect_qb(db, user):
    db.session.add(QuickBooksConnection(
        user_id=user.id, realm_id='R1', access_token='tok', refresh_token='r', is_active=True))


# ── unit: helpers ────────────────────────────────────────────────────────────
def test_tax_noun_prefers_type_then_region():
    assert tax_noun(types.SimpleNamespace(tax_type='GST', country='United Kingdom')) == 'GST'
    assert tax_noun(types.SimpleNamespace(tax_type=None, country='Jersey')) == 'GST'
    assert tax_noun(types.SimpleNamespace(tax_type=None, country='United Kingdom')) == 'VAT'
    assert tax_noun(types.SimpleNamespace(tax_type=None, country=None)) == 'VAT'


def test_picked_but_not_registered_predicate():
    assert picked_but_not_registered(types.SimpleNamespace(output_tax_code_ref='2', tax_registered=False)) is True
    assert picked_but_not_registered(types.SimpleNamespace(output_tax_code_ref='2', tax_registered=True)) is False
    assert picked_but_not_registered(types.SimpleNamespace(output_tax_code_ref=None, tax_registered=False)) is False


# ── save_tax: tax_rate ownership ─────────────────────────────────────────────
def test_save_tax_connected_does_not_touch_rate(app, db, user):
    app.config['WTF_CSRF_ENABLED'] = False
    _connect_qb(db, user)
    user.tax_rate = Decimal('5')          # owned by the picker
    user.output_tax_code_ref = '2'
    _active_plan(db, user)

    client = app.test_client(); _login(client, user)
    # No tax_rate field submitted; a tampered rate must also be ignored when connected.
    resp = client.post('/settings/tax', data={'tax_registered': 'true', 'tax_type': 'GST',
                                              'tax_number': '0001234', 'tax_rate': '99'}, headers=_HTTPS)
    assert resp.status_code == 302
    u = db.session.get(User, user.id)
    assert u.tax_registered is True
    assert u.tax_type == 'GST'
    assert u.tax_rate == Decimal('5')     # untouched — picker owns it, not zeroed/overwritten


def test_save_tax_not_connected_saves_manual_rate(app, db, user):
    app.config['WTF_CSRF_ENABLED'] = False
    _active_plan(db, user)                # no QB/Xero connection
    client = app.test_client(); _login(client, user)
    resp = client.post('/settings/tax', data={'tax_registered': 'true', 'tax_type': 'VAT',
                                              'tax_rate': '20'}, headers=_HTTPS)
    assert resp.status_code == 302
    u = db.session.get(User, user.id)
    assert u.tax_registered is True and u.tax_type == 'VAT' and u.tax_rate == Decimal('20')


def test_save_tax_not_connected_zero_rate_rejected(app, db, user):
    app.config['WTF_CSRF_ENABLED'] = False
    _active_plan(db, user)
    client = app.test_client(); _login(client, user)
    resp = client.post('/settings/tax', data={'tax_registered': 'true', 'tax_type': 'GST',
                                              'tax_rate': '0'}, headers=_HTTPS)
    assert resp.status_code == 302
    # Guard rolled back -> registration not persisted (a registered user must have a rate).
    assert db.session.get(User, user.id).tax_registered is False


def test_save_tax_unregister(app, db, user):
    app.config['WTF_CSRF_ENABLED'] = False
    user.tax_registered = True
    _active_plan(db, user)
    client = app.test_client(); _login(client, user)
    resp = client.post('/settings/tax', data={}, headers=_HTTPS)  # checkbox unchecked -> absent
    assert resp.status_code == 302
    assert db.session.get(User, user.id).tax_registered is False


# ── Settings page: warning + region label ────────────────────────────────────
def test_settings_warns_picked_but_not_registered_with_gst_label(app, db, user):
    _connect_qb(db, user)
    user.output_tax_code_ref = '2'
    user.output_tax_code_name = 'GST'
    user.output_tax_provider = 'quickbooks'
    user.tax_registered = False
    user.country = 'Jersey'
    _active_plan(db, user)

    client = app.test_client(); _login(client, user)
    html = client.get('/settings/', headers=_HTTPS).get_data(as_text=True)
    assert 'GST Registered' in html                 # region-derived label, not "VAT"
    assert "aren’t marked" in html or "won’t apply on sync" in html  # picked-but-not-registered warning


# ── reports.py /api/vat gate migrated to tax_registered ──────────────────────
def test_api_vat_gate_uses_tax_registered(app, db, user):
    _active_plan(db, user)
    client = app.test_client(); _login(client, user)

    user.tax_registered = False; db.session.commit()
    r = client.get('/reports/api/vat?date_from=2026-01-01&date_to=2026-03-31', headers=_HTTPS)
    assert r.status_code == 400 and r.get_json()['error'] == 'Not tax registered'

    user.tax_registered = True; db.session.commit()
    r = client.get('/reports/api/vat?date_from=2026-01-01&date_to=2026-03-31', headers=_HTTPS)
    assert r.get_json().get('error') != 'Not tax registered'   # gate passed (now keyed off tax_registered)
