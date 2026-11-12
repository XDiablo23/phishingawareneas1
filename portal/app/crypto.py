"""
Encryption at rest for the portal's own secret columns (Setting.
pa_service_token, TicketConfig.auth_header_value).

Mirrors backend/app/crypto.py exactly (same TypeDecorator approach, same
Fernet choice) - the two services are separate deployable codebases (see
PORTAL_GUIDE.md - own database, own venv-compatible requirements.txt) so
this is intentionally a small, self-contained duplicate rather than a
cross-service import.

The portal has no Alembic (schema is managed by Base.metadata.create_all()
on every boot, see app/db.py:init_db). `ensure_secrets_encrypted()` is the
portal's equivalent of the backend's data-migration: an idempotent startup
step (called from main.py's lifespan, right alongside the existing
ensure_seed()) that backfills any legacy plaintext value left over from
before these columns used EncryptedSecret.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text, column, select, table, update
from sqlalchemy.types import TypeDecorator

from app.config import settings

_ENCRYPTED_PREFIX = "gAAAAA"  # see backend/app/crypto.py for why this is reliable


class CryptoError(Exception):
    pass


def _fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def looks_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def encrypt(value: str | None) -> str | None:
    if not value:
        return value
    if looks_encrypted(value):
        return value
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return value
    if not looks_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as e:
        raise CryptoError(
            "failed to decrypt a stored secret - PORTAL_ENCRYPTION_KEY may "
            "have changed since it was saved") from e


class EncryptedSecret(TypeDecorator):
    """A Text column that transparently encrypts on write and decrypts on
    read. Application code never sees ciphertext."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)


# (table, singleton id, column) for every secret column - checked via a
# Core table()/column() construct (not string-built SQL) that bypasses
# EncryptedSecret's own transparent decryption, so it can tell whether the
# stored bytes are still plaintext.
_SECRET_FIELDS = [
    ("settings", "singleton", "pa_service_token"),
    ("ticket_config", "singleton", "auth_header_value"),
]


def ensure_secrets_encrypted(db) -> None:
    """Backfill: encrypt any legacy plaintext secret left over from before
    its column used EncryptedSecret. Safe to call on every boot - a value
    that's already encrypted, or a row that doesn't exist yet, is left
    untouched, so this never writes anything after the first successful
    run for a given value."""
    changed = False
    for table_name, row_id, col_name in _SECRET_FIELDS:
        tbl = table(table_name, column("id", String), column(col_name, Text))
        raw = db.execute(select(tbl.c[col_name]).where(tbl.c.id == row_id)).scalar()
        if raw and not looks_encrypted(raw):
            db.execute(
                update(tbl).where(tbl.c.id == row_id).values({col_name: encrypt(raw)}))
            changed = True
    if changed:
        db.commit()
