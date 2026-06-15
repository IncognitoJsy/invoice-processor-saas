"""Shared symmetric encryption for integration tokens at rest.

All integration OAuth tokens (QuickBooks, Xero) are Fernet-encrypted with a
single key, ``TOKEN_ENCRYPTION_KEY``. Presence and validity of that key is
enforced at startup (see ``app.security.encryption_keys``), so the runtime
helpers here assume it is set and never silently fall back to plaintext when
*encrypting*.

Decryption keeps a deliberate plaintext fallback: rows written before tokens
were encrypted (e.g. existing Xero tokens) are not Fernet ciphertext, so
``decrypt_token`` returns them unchanged. Those rows self-heal — they are
re-stored as ciphertext on the next token refresh.
"""
import os

from cryptography.fernet import Fernet, InvalidToken


def _cipher():
    key = os.environ.get('TOKEN_ENCRYPTION_KEY')
    if not key:
        # Should be unreachable: validate_encryption_keys() fails startup if the
        # key is missing. Guard anyway so we never silently store plaintext.
        raise RuntimeError('TOKEN_ENCRYPTION_KEY is not set')
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext_token):
    """Encrypt a token for storage. Empty/None passed through unchanged."""
    if not plaintext_token:
        return plaintext_token
    return _cipher().encrypt(plaintext_token.encode()).decode()


def decrypt_token(stored_token):
    """Decrypt a stored token.

    Returns empty/None unchanged. If the value is not valid ciphertext (a
    pre-encryption plaintext row), it is returned as-is so existing tokens keep
    working until the next refresh re-encrypts them.
    """
    if not stored_token:
        return stored_token
    try:
        return _cipher().decrypt(stored_token.encode()).decode()
    except InvalidToken:
        return stored_token
