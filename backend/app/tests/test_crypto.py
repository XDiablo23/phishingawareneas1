"""
Encryption-at-rest tests: the pure encrypt/decrypt helpers, and an ORM-level
round trip proving Tenant's secret columns transparently encrypt on write
and decrypt on read through EncryptedSecret.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.db.base as base
base.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool, future=True)
base.SessionLocal.configure(bind=base.engine)

from app.db.base import init_db  # noqa: E402
from app.db import models as m  # noqa: E402
from app import crypto  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _db():
    init_db()


def test_encrypt_decrypt_round_trip():
    ct = crypto.encrypt("super-secret-value")
    assert ct != "super-secret-value"
    assert crypto.looks_encrypted(ct)
    assert crypto.decrypt(ct) == "super-secret-value"


def test_encrypt_is_idempotent():
    ct = crypto.encrypt("a-value")
    assert crypto.encrypt(ct) == ct  # already encrypted -> returned unchanged


def test_decrypt_passes_through_legacy_plaintext():
    """A value from before this column was migrated to EncryptedSecret must
    keep working (returned as-is) rather than raising."""
    assert crypto.decrypt("plain-old-secret") == "plain-old-secret"


def test_none_and_empty_pass_through():
    assert crypto.encrypt(None) is None
    assert crypto.encrypt("") == ""
    assert crypto.decrypt(None) is None
    assert crypto.decrypt("") == ""


def test_decrypt_tampered_token_raises():
    ct = crypto.encrypt("value")
    tampered = ct[:-4] + "abcd"  # corrupt the trailing HMAC/ciphertext bytes
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(tampered)


def test_tenant_secret_columns_round_trip_through_orm():
    """The whole point: application code (routes_manage.py, gophish_sync.py,
    etc.) reads/writes plain strings on Tenant.*, never touching crypto.py
    directly - only the raw DB row should ever contain ciphertext."""
    s = base.SessionLocal()
    try:
        t = m.Tenant(
            name="Crypto Test Co",
            webhook_secret="wh-abc123",
            ingest_token="ing-def456",
            gophish_api_key="gp-key-789",
            entra_client_secret="entra-secret",
            ldap_bind_password="ldap-pw",
        )
        s.add(t)
        s.commit()
        tid = t.id
    finally:
        s.close()

    # A textual query (not bound to the typed Column objects) bypasses
    # EncryptedSecret.process_result_value entirely, so this sees exactly
    # the bytes actually stored on disk - querying through the mapped Table
    # or ORM would decrypt transparently even here, which isn't the point.
    with base.engine.connect() as conn:
        raw = conn.execute(
            text("SELECT webhook_secret, gophish_api_key FROM tenants WHERE id = :id"),
            {"id": tid}).fetchone()
    assert raw.webhook_secret != "wh-abc123"
    assert raw.webhook_secret.startswith("gAAAAA")
    assert raw.gophish_api_key.startswith("gAAAAA")

    # a fresh session/query decrypts transparently back to plaintext
    s2 = base.SessionLocal()
    try:
        t2 = s2.query(m.Tenant).filter_by(id=tid).first()
        assert t2.webhook_secret == "wh-abc123"
        assert t2.ingest_token == "ing-def456"
        assert t2.gophish_api_key == "gp-key-789"
        assert t2.entra_client_secret == "entra-secret"
        assert t2.ldap_bind_password == "ldap-pw"
    finally:
        s2.close()
