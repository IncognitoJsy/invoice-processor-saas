"""Tests for the PayPal webhook signature gating (AUDIT risk #2).

Two layers:
  * Route tests exercise /billing/webhook with verify_webhook_signature stubbed,
    proving the handler refuses to act on unverified events and that the
    existing state machine still runs once verification passes.
  * Unit tests exercise PayPalService.verify_webhook_signature itself with the
    PayPal API call mocked, proving it fails closed and maps PayPal's
    verification_status to a boolean.

No real PayPal calls are made. There are no PayPal sample-webhook fixtures in
the repo, so these prove the *gating logic*, not real signature math — that can
only be confirmed against staging once PAYPAL_WEBHOOK_ID is set.
"""
import pytest

import app.web.billing as billing_module
from app.services.paypal_service import PayPalService


# HTTPS is enforced in this app; the test client must present a forwarded-proto
# header to avoid a 301 to https (same idiom as test_validator_pipeline).
_HTTPS = {'X-Forwarded-Proto': 'https'}


class _StubPayPal:
    """Stands in for the PayPalService returned by get_paypal_service()."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def verify_webhook_signature(self, headers, body):
        self.calls.append((headers, body))
        return self._result


@pytest.fixture
def stub_verify(monkeypatch):
    """Patch get_paypal_service() in the billing module to a controllable stub."""

    def _install(result):
        stub = _StubPayPal(result)
        monkeypatch.setattr(billing_module, 'get_paypal_service', lambda: stub)
        return stub

    return _install


def _activated_event(user_id, plan='pro', frequency='monthly', sub_id='I-SUB123'):
    return {
        'event_type': 'BILLING.SUBSCRIPTION.ACTIVATED',
        'resource': {
            'id': sub_id,
            'custom_id': f'user_{user_id}_plan_{plan}_{frequency}',
        },
    }


# --- Route-level gating -----------------------------------------------------

def test_forged_event_is_rejected_and_user_unchanged(app, user, db, stub_verify):
    """The core security assertion: a failed verification must not mutate state."""
    stub_verify((False, 'Signature mismatch'))
    user.subscription_plan = 'free'
    db.session.commit()

    client = app.test_client()
    resp = client.post('/billing/webhook', json=_activated_event(user.id, plan='pro'),
                       headers=_HTTPS)

    assert resp.status_code == 401
    from app.models.user import User
    assert User.query.get(user.id).subscription_plan == 'free'


def test_valid_activated_event_upgrades_user(app, user, db, stub_verify):
    stub_verify((True, None))

    client = app.test_client()
    resp = client.post('/billing/webhook', json=_activated_event(user.id, plan='pro'),
                       headers=_HTTPS)

    assert resp.status_code == 200
    from app.models.user import User
    refreshed = User.query.get(user.id)
    assert refreshed.subscription_plan == 'pro'
    assert refreshed.subscription_status == 'active'
    assert refreshed.paypal_subscription_id == 'I-SUB123'


def test_valid_cancelled_event_marks_cancelled(app, user, db, stub_verify):
    user.paypal_subscription_id = 'I-SUB123'
    user.subscription_plan = 'pro'
    user.subscription_status = 'active'
    db.session.commit()
    stub_verify((True, None))

    client = app.test_client()
    resp = client.post('/billing/webhook', json={
        'event_type': 'BILLING.SUBSCRIPTION.CANCELLED',
        'resource': {'id': 'I-SUB123'},
    }, headers=_HTTPS)

    assert resp.status_code == 200
    from app.models.user import User
    assert User.query.get(user.id).subscription_status == 'cancelled'


def test_invalid_json_body_is_rejected(app, stub_verify):
    stub_verify((True, None))  # never reached
    client = app.test_client()
    resp = client.post('/billing/webhook', data='not json',
                       content_type='application/json', headers=_HTTPS)
    assert resp.status_code == 400


# --- verify_webhook_signature unit behaviour --------------------------------

_HEADERS = {
    'PAYPAL-AUTH-ALGO': 'SHA256withRSA',
    'PAYPAL-CERT-URL': 'https://api.paypal.com/cert',
    'PAYPAL-TRANSMISSION-ID': 'tx-1',
    'PAYPAL-TRANSMISSION-SIG': 'sig-1',
    'PAYPAL-TRANSMISSION-TIME': '2026-06-15T00:00:00Z',
}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _service(monkeypatch):
    svc = PayPalService()
    # Avoid real OAuth token fetch when verify builds its headers.
    monkeypatch.setattr(svc, '_headers', lambda: {})
    return svc


def test_verify_fails_closed_without_webhook_id(app, monkeypatch):
    monkeypatch.delenv('PAYPAL_WEBHOOK_ID', raising=False)
    with app.app_context():
        ok, err = _service(monkeypatch).verify_webhook_signature(_HEADERS, {})
    assert ok is False and 'not configured' in err


def test_verify_fails_when_headers_missing(app, monkeypatch):
    monkeypatch.setenv('PAYPAL_WEBHOOK_ID', 'WH-1')
    with app.app_context():
        ok, err = _service(monkeypatch).verify_webhook_signature({}, {})
    assert ok is False and 'Missing transmission headers' in err


def test_verify_success_status_passes(app, monkeypatch):
    monkeypatch.setenv('PAYPAL_WEBHOOK_ID', 'WH-1')
    monkeypatch.setattr('app.services.paypal_service.requests.post',
                        lambda *a, **k: _FakeResponse(200, {'verification_status': 'SUCCESS'}))
    with app.app_context():
        ok, err = _service(monkeypatch).verify_webhook_signature(_HEADERS, {'event_type': 'x'})
    assert ok is True and err is None


def test_verify_failure_status_is_rejected(app, monkeypatch):
    monkeypatch.setenv('PAYPAL_WEBHOOK_ID', 'WH-1')
    monkeypatch.setattr('app.services.paypal_service.requests.post',
                        lambda *a, **k: _FakeResponse(200, {'verification_status': 'FAILURE'}))
    with app.app_context():
        ok, err = _service(monkeypatch).verify_webhook_signature(_HEADERS, {'event_type': 'x'})
    assert ok is False and 'FAILURE' in err
