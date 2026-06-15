"""Encryption-key handling tests (AUDIT risk #3).

Covers:
  * validate_encryption_keys: fail-hard when a required key is missing/invalid,
    pass when valid, and skip-with-injected-keys under TESTING.
  * token_crypto: encrypt/decrypt round-trip and the plaintext fallback that
    lets pre-encryption (e.g. existing Xero) rows self-heal on next write.
  * Xero: stored tokens are ciphertext and read back decrypted; legacy
    plaintext rows still read.
  * Email: an undecryptable token flags the connection needs_reconnect instead
    of raising.
"""
import os
from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from app.security.encryption_keys import validate_encryption_keys, REQUIRED_KEYS
from app.services.token_crypto import encrypt_token, decrypt_token

_VALID = 'fQKvP3Vok635KL-XmzhwQPz_bfac2FRrvMschKOeoVY='


class _FakeApp:
    def __init__(self, testing):
        self.config = {'TESTING': testing}


# --- validate_encryption_keys ----------------------------------------------

def test_startup_fails_when_a_key_is_missing(monkeypatch):
    for k in REQUIRED_KEYS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError) as exc:
        validate_encryption_keys(_FakeApp(testing=False))
    assert 'TOKEN_ENCRYPTION_KEY' in str(exc.value)


def test_startup_fails_when_a_key_is_invalid(monkeypatch):
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', 'not-a-valid-fernet-key')
    monkeypatch.setenv('EMAIL_TOKEN_ENCRYPTION_KEY', _VALID)
    with pytest.raises(RuntimeError) as exc:
        validate_encryption_keys(_FakeApp(testing=False))
    assert 'not a valid Fernet key' in str(exc.value)


def test_startup_passes_with_valid_keys(monkeypatch):
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', _VALID)
    monkeypatch.setenv('EMAIL_TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode())
    validate_encryption_keys(_FakeApp(testing=False))  # must not raise


def test_testing_mode_injects_keys_and_skips_check(monkeypatch):
    for k in REQUIRED_KEYS:
        monkeypatch.delenv(k, raising=False)
    validate_encryption_keys(_FakeApp(testing=True))  # must not raise
    for k in REQUIRED_KEYS:
        assert os.environ.get(k)  # injected


# --- token_crypto -----------------------------------------------------------

def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', _VALID)
    ciphertext = encrypt_token('xero-access-token')
    assert ciphertext != 'xero-access-token'           # actually encrypted
    assert decrypt_token(ciphertext) == 'xero-access-token'


def test_decrypt_passes_through_plaintext(monkeypatch):
    """Pre-encryption rows (legacy plaintext) decrypt to themselves."""
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', _VALID)
    assert decrypt_token('legacy-plaintext-token') == 'legacy-plaintext-token'


def test_empty_values_pass_through(monkeypatch):
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY', _VALID)
    assert encrypt_token('') == ''
    assert encrypt_token(None) is None
    assert decrypt_token('') == ''
    assert decrypt_token(None) is None


# --- Xero token storage -----------------------------------------------------

def test_xero_get_valid_token_decrypts_stored_token(app):
    """Non-expired connection: _get_valid_token returns the decrypted token."""
    from app.integrations.xero_service import XeroService
    conn = SimpleNamespace(
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
        access_token=encrypt_token('plain-access'),
        refresh_token=encrypt_token('plain-refresh'),
    )
    assert conn.access_token != 'plain-access'          # stored encrypted
    assert XeroService()._get_valid_token(conn) == 'plain-access'


def test_xero_get_valid_token_reads_legacy_plaintext(app):
    """A pre-migration plaintext token is still usable (self-heals on refresh)."""
    from app.integrations.xero_service import XeroService
    conn = SimpleNamespace(
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
        access_token='legacy-plain-access',
        refresh_token='legacy-plain-refresh',
    )
    assert XeroService()._get_valid_token(conn) == 'legacy-plain-access'


# --- Email token reconnect handling -----------------------------------------

def test_email_token_undecryptable_flags_reconnect(app, db):
    from app.models.user import User
    from app.models.email_connection import EmailConnection

    u = User(email='mail@x', password_hash='x')
    db.session.add(u)
    db.session.commit()

    conn = EmailConnection(user_id=u.id, provider='gmail', email_address='mail@x')
    conn.set_token({'access_token': 'abc', 'refresh_token': 'def'})
    db.session.add(conn)
    db.session.commit()

    # Round-trips fine under the current key.
    assert conn.get_token() == {'access_token': 'abc', 'refresh_token': 'def'}

    # Simulate the key having changed (the old auto-generated key is lost).
    os.environ['EMAIL_TOKEN_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    try:
        assert conn.get_token() is None          # graceful, not an exception
        assert conn.needs_reconnect is True
        assert conn.is_active is False
        assert EmailConnection.query.get(conn.id).needs_reconnect is True
    finally:
        # Restore the testing key so later tests are unaffected.
        from app.security.encryption_keys import _TEST_KEYS
        os.environ['EMAIL_TOKEN_ENCRYPTION_KEY'] = _TEST_KEYS['EMAIL_TOKEN_ENCRYPTION_KEY']
