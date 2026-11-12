"""
Encryption at rest for secret columns (Tenant.webhook_secret, ingest_token,
gophish_api_key, entra_client_secret, ldap_bind_password).

These were plaintext String columns - "write-only" only in the sense that
the API never echoes them back, but the raw value sat unencrypted in the
database. `EncryptedSecret` is a SQLAlchemy TypeDecorator that makes this
transparent: application code reads and writes plain strings exactly as
before (no call site changes needed anywhere in integrations/ or
routes_manage.py), while the column itself only ever stores Fernet
ciphertext.

Fernet (symmetric, authenticated) is used rather than a bespoke scheme
because it's a reviewed, standard construction with no configuration
footguns (fixed algorithm, built-in integrity check, key rotation via
MultiFernet if ever needed) - appropriate for "protect this at rest without
standing up a secrets manager," which is the stated scope here (see
SECURITY.md).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import settings

# Every Fernet token is base64(version_byte=0x80 || ...), and that leading
# byte always encodes to this fixed 6-character prefix - a reliable, well-
# known way to tell "already encrypted" from "still plaintext" without a
# separate marker column. https://github.com/fernet/spec (token format).
_ENCRYPTED_PREFIX = "gAAAAA"


class CryptoError(Exception):
    pass


def _fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def looks_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def encrypt(value: str | None) -> str | None:
    """Encrypt a plaintext secret for storage. None/empty pass through
    unchanged (nothing to protect). Idempotent: a value that already looks
    encrypted is returned as-is, so re-saving an unchanged secret (or
    re-running the backfill migration) never double-wraps it."""
    if not value:
        return value
    if looks_encrypted(value):
        return value
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """Decrypt a stored secret back to plaintext. None/empty pass through.
    A value that doesn't look encrypted is returned as-is - this is what
    lets a legacy plaintext row (from before its column was migrated to
    EncryptedSecret) keep working until it's next re-saved, instead of
    hard-failing on old data."""
    if not value:
        return value
    if not looks_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise CryptoError(
            "failed to decrypt a stored secret - ENCRYPTION_KEY may have "
            "changed since it was saved") from e


class EncryptedSecret(TypeDecorator):
    """A Text column that transparently encrypts on write and decrypts on
    read. Application code never sees ciphertext."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
