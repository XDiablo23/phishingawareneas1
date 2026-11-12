"""encrypt tenant secret columns at rest

Widens the five per-tenant secret columns (webhook_secret, ingest_token,
gophish_api_key, entra_client_secret, ldap_bind_password) from VARCHAR(N) to
TEXT - Fernet ciphertext is longer than the plaintext it replaces, so the
old VARCHAR caps are no longer wide enough - then encrypts any existing
plaintext value in place using the application's own encrypt() helper.

Idempotent: a value that already looks like a Fernet token (every Fernet
token starts with the fixed "gAAAAA" prefix) is left untouched by encrypt(),
so re-running this migration, or running it against a database that already
has encrypted values, is safe. ENCRYPTION_KEY must be set to the same value
the application uses, or newly-encrypted values won't decrypt later.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column name, original VARCHAR length - only needed for the downgrade path)
_SECRET_COLUMNS = [
    ("webhook_secret", 64),
    ("ingest_token", 64),
    ("gophish_api_key", 128),
    ("entra_client_secret", 256),
    ("ldap_bind_password", 256),
]


def _tenants_table():
    cols = [sa.column("id", sa.String)] + [
        sa.column(name, sa.Text) for name, _ in _SECRET_COLUMNS]
    return sa.table("tenants", *cols)


def _rewrite(transform) -> None:
    """Apply `transform` (encrypt or decrypt) to every non-empty secret
    column value, writing back only the rows that actually changed."""
    bind = op.get_bind()
    tenants = _tenants_table()
    names = [name for name, _ in _SECRET_COLUMNS]
    rows = bind.execute(
        sa.select(tenants.c.id, *[tenants.c[n] for n in names])).fetchall()
    for row in rows:
        values = dict(zip(["id"] + names, row))
        transformed = {n: transform(values[n]) for n in names if values[n]}
        updates = {n: v for n, v in transformed.items() if v != values[n]}
        if updates:
            bind.execute(
                tenants.update().where(tenants.c.id == values["id"]).values(**updates))


def upgrade() -> None:
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, _old_len in _SECRET_COLUMNS:
            batch_op.alter_column(name, type_=sa.Text(), existing_nullable=True)

    from app.crypto import encrypt  # app/ is on sys.path via migrations/env.py
    _rewrite(encrypt)


def downgrade() -> None:
    from app.crypto import decrypt
    _rewrite(decrypt)

    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, old_len in _SECRET_COLUMNS:
            batch_op.alter_column(
                name, type_=sa.String(length=old_len), existing_nullable=True)
