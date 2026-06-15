"""Startup validation of the encryption keys used for tokens at rest.

Integration tokens (QuickBooks, Xero) and email/IMAP credentials are encrypted
with Fernet keys supplied via environment variables. Historically a missing key
was handled by silently storing plaintext (QuickBooks) or auto-generating an
ephemeral key (email) — the latter bricked every stored credential on the next
restart. Both are now impossible: ``validate_encryption_keys`` fails the boot if
a required key is absent or not a valid Fernet key.

Under TESTING the checks are skipped and deterministic keys are injected, so the
encryption code paths work without real secrets in the test environment.
"""
import os

from cryptography.fernet import Fernet

# Keys that must be present and valid for the app to start.
REQUIRED_KEYS = ('TOKEN_ENCRYPTION_KEY', 'EMAIL_TOKEN_ENCRYPTION_KEY')

# Fixed, throwaway keys used ONLY when app.config['TESTING'] is set. They are not
# secret and must never be used outside tests.
_TEST_KEYS = {
    'TOKEN_ENCRYPTION_KEY': 'fQKvP3Vok635KL-XmzhwQPz_bfac2FRrvMschKOeoVY=',
    'EMAIL_TOKEN_ENCRYPTION_KEY': 'wqWKIXeIsEv-VUDrkrLlFzpRo8yH0c4NEdoa2BM2K80=',
}


def _is_valid_fernet_key(value):
    try:
        Fernet(value.encode() if isinstance(value, str) else value)
        return True
    except (ValueError, TypeError):
        return False


def validate_encryption_keys(app):
    """Ensure required encryption keys are present and valid, or fail hard.

    In TESTING mode, inject deterministic keys and skip the hard check so the
    suite runs without real secrets. Otherwise raise RuntimeError listing every
    missing or invalid key, aborting startup.
    """
    if app.config.get('TESTING'):
        for name, key in _TEST_KEYS.items():
            os.environ.setdefault(name, key)
        return

    problems = []
    for name in REQUIRED_KEYS:
        value = os.environ.get(name)
        if not value:
            problems.append(f"{name} is not set")
        elif not _is_valid_fernet_key(value):
            problems.append(f"{name} is not a valid Fernet key")

    if problems:
        raise RuntimeError(
            "Refusing to start: encryption key configuration is invalid — "
            + "; ".join(problems)
            + ". Generate a key with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" and set it in the "
            "environment (Railway variables). Tokens must never be stored "
            "unencrypted or under an auto-generated key."
        )
