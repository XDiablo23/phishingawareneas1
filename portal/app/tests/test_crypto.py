"""
Portal encryption-at-rest tests: the pure encrypt/decrypt helpers, an
ORM-level round trip through Setting/TicketConfig, and the
ensure_secrets_encrypted() startup backfill (which the `client` fixture
never exercises, since conftest.py's client skips the app lifespan).
"""
from sqlalchemy import text

import app.db as dbm
from app import crypto
from app import models as m


def test_encrypt_decrypt_round_trip():
    ct = crypto.encrypt("super-secret-value")
    assert ct != "super-secret-value"
    assert crypto.looks_encrypted(ct)
    assert crypto.decrypt(ct) == "super-secret-value"


def test_encrypt_is_idempotent():
    ct = crypto.encrypt("a-value")
    assert crypto.encrypt(ct) == ct


def test_decrypt_passes_through_legacy_plaintext():
    assert crypto.decrypt("plain-old-secret") == "plain-old-secret"


def test_none_and_empty_pass_through():
    assert crypto.encrypt(None) is None
    assert crypto.encrypt("") == ""
    assert crypto.decrypt(None) is None
    assert crypto.decrypt("") == ""


def test_patch_schema_scrubs_legacy_service_credentials(tmp_path, monkeypatch):
    """A portal.db created before the service-token change still holds the
    operator's email and PLAINTEXT password in the two columns the token
    replaced. Nothing reads them any more and ensure_secrets_encrypted() only
    touches columns still in the model, so the upgrade path itself has to
    blank them - otherwise the credential sits on disk indefinitely."""
    from sqlalchemy import create_engine

    from app.config import settings as cfg

    db_path = tmp_path / "legacy_portal.db"
    url = f"sqlite:///{db_path}"
    legacy_engine = create_engine(url, future=True)

    # Rebuild the pre-token schema: no pa_service_token, credentials present.
    with legacy_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE settings ("
            " id TEXT PRIMARY KEY, pa_base_url TEXT, pa_tenant_id TEXT,"
            " pa_service_email TEXT, pa_service_password TEXT)")
        conn.exec_driver_sql(
            "INSERT INTO settings (id, pa_base_url, pa_tenant_id,"
            " pa_service_email, pa_service_password) VALUES"
            " ('singleton', 'http://pa.example', 't-1',"
            " 'operator@corp.example', 'PlaintextOperatorPassw0rd')")

    monkeypatch.setattr(dbm, "engine", legacy_engine)
    monkeypatch.setattr(cfg, "DATABASE_URL", url)
    dbm._patch_schema()

    with legacy_engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(settings)")}
        row = conn.exec_driver_sql(
            "SELECT pa_service_email, pa_service_password FROM settings"
        ).fetchone()

    assert "pa_service_token" in cols, "upgrade did not add the token column"
    assert row == (None, None), "legacy operator credential survived the upgrade"


def test_decrypt_tampered_token_raises():
    ct = crypto.encrypt("value")
    tampered = ct[:-4] + "abcd"
    try:
        crypto.decrypt(tampered)
        assert False, "expected CryptoError"
    except crypto.CryptoError:
        pass


def test_setting_and_ticketconfig_round_trip_through_orm():
    s = dbm.SessionLocal()
    try:
        setting = m.Setting(id="singleton", pa_service_token="pa-token-123")
        ticket = m.TicketConfig(id="singleton", auth_header_value="Bearer tok-456")
        s.merge(setting)
        s.merge(ticket)
        s.commit()
    finally:
        s.close()

    # a textual query bypasses EncryptedSecret's process_result_value, so
    # this sees exactly what's stored on disk
    with dbm.engine.connect() as conn:
        raw_token = conn.execute(
            text("SELECT pa_service_token FROM settings WHERE id='singleton'")
        ).scalar()
        raw_hdr = conn.execute(
            text("SELECT auth_header_value FROM ticket_config WHERE id='singleton'")
        ).scalar()
    assert raw_token != "pa-token-123" and raw_token.startswith("gAAAAA")
    assert raw_hdr != "Bearer tok-456" and raw_hdr.startswith("gAAAAA")

    s2 = dbm.SessionLocal()
    try:
        setting2 = s2.query(m.Setting).filter_by(id="singleton").first()
        ticket2 = s2.query(m.TicketConfig).filter_by(id="singleton").first()
        assert setting2.pa_service_token == "pa-token-123"
        assert ticket2.auth_header_value == "Bearer tok-456"
    finally:
        s2.close()


def test_ensure_secrets_encrypted_backfills_legacy_plaintext():
    """Simulates a pre-existing portal.db with plaintext secrets (as if
    written before these columns used EncryptedSecret) by inserting via raw
    SQL, bypassing the ORM's encrypt-on-write entirely."""
    # ensure_seed() (run by the autouse _reset_db fixture) already creates
    # the empty singleton rows, matching how they'd exist in a real
    # pre-existing portal.db - so this is an UPDATE, not an INSERT.
    with dbm.engine.begin() as conn:
        conn.execute(text(
            "UPDATE settings SET pa_service_token = 'legacy-plaintext-token' "
            "WHERE id = 'singleton'"))
        conn.execute(text(
            "UPDATE ticket_config SET auth_header_value = 'legacy-plaintext-hdr' "
            "WHERE id = 'singleton'"))

    s = dbm.SessionLocal()
    try:
        crypto.ensure_secrets_encrypted(s)
    finally:
        s.close()

    with dbm.engine.connect() as conn:
        raw_token = conn.execute(
            text("SELECT pa_service_token FROM settings WHERE id='singleton'")
        ).scalar()
        raw_hdr = conn.execute(
            text("SELECT auth_header_value FROM ticket_config WHERE id='singleton'")
        ).scalar()
    assert raw_token != "legacy-plaintext-token" and raw_token.startswith("gAAAAA")
    assert raw_hdr != "legacy-plaintext-hdr" and raw_hdr.startswith("gAAAAA")

    # decrypts back correctly through the ORM
    s2 = dbm.SessionLocal()
    try:
        setting = s2.query(m.Setting).filter_by(id="singleton").first()
        ticket = s2.query(m.TicketConfig).filter_by(id="singleton").first()
        assert setting.pa_service_token == "legacy-plaintext-token"
        assert ticket.auth_header_value == "legacy-plaintext-hdr"
    finally:
        s2.close()

    # idempotent: running it again doesn't error and leaves values decryptable
    s3 = dbm.SessionLocal()
    try:
        crypto.ensure_secrets_encrypted(s3)
        setting = s3.query(m.Setting).filter_by(id="singleton").first()
        assert setting.pa_service_token == "legacy-plaintext-token"
    finally:
        s3.close()
