"""
Tests for pa_client.py's real implementation - the fake_pa fixture used
everywhere else replaces every public function wholesale, so nothing else
in this suite exercises resolve_conn()/_req()/PAConn at all. This covers
the actual service-token header (X-Portal-Token), the token/tenant-id
"not configured" guard, and error propagation on a non-2xx response.
"""
import httpx
import pytest

import app.db as dbm
from app import models as m
from app import pa_client as pa
from app.tests.conftest import set_setting


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.text = text or ""
        self.content = b"1" if json_body is not None else b""

    def json(self):
        return self._json


def test_resolve_conn_reads_setting_token(client):
    set_setting()  # ensures the singleton row exists
    db = dbm.SessionLocal()
    try:
        s = db.query(m.Setting).filter_by(id="singleton").first()
        s.pa_base_url = "https://pa.example"
        s.pa_tenant_id = "T-123"
        s.pa_service_token = "the-service-token"
        db.commit()

        conn = pa.resolve_conn(db)
        assert conn.base_url == "https://pa.example"
        assert conn.tenant_id == "T-123"
        assert conn.token == "the-service-token"
        assert conn.portal_base == "/api/v1/tenants/T-123/portal"
    finally:
        db.close()


def test_req_sends_portal_token_header(client, monkeypatch):
    captured = {}

    def fake_request(method, url, headers=None, **kw):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)

    conn = pa.PAConn("https://pa.example", "T-1", "tok-abc")
    out = pa._req(conn, "GET", "/api/v1/tenants/T-1/portal/employees")

    assert out == {"ok": True}
    assert captured["headers"]["X-Portal-Token"] == "tok-abc"
    assert captured["url"] == "https://pa.example/api/v1/tenants/T-1/portal/employees"


def test_req_raises_paerror_on_error_status(monkeypatch):
    def fake_request(method, url, headers=None, **kw):
        return _FakeResponse(401, text="invalid or missing portal service token")

    monkeypatch.setattr(httpx, "request", fake_request)

    conn = pa.PAConn("https://pa.example", "T-1", "wrong-token")
    with pytest.raises(pa.PAError):
        pa._req(conn, "GET", "/api/v1/tenants/T-1/portal/employees")


def test_req_rejects_unconfigured_connection():
    conn = pa.PAConn("https://pa.example", "", "")  # no token, no tenant_id
    with pytest.raises(pa.PAError):
        pa._req(conn, "GET", "/x")

    conn2 = pa.PAConn("https://pa.example", "T-1", "")  # token missing
    with pytest.raises(pa.PAError):
        pa._req(conn2, "GET", "/x")


def test_login_verify_unaffected_by_service_token_change(monkeypatch):
    """login_verify() is the separate, human delegated-login concern and
    must keep POSTing email/password to /auth/login regardless of the
    service-token rework."""
    captured = {}

    def fake_post(url, data=None, timeout=None, verify=None):
        captured["url"] = url
        captured["data"] = data
        return _FakeResponse(200, {"role": "operator", "tenant_id": "T-1"})

    monkeypatch.setattr(httpx, "post", fake_post)

    out = pa.login_verify("https://pa.example", "admin@acme.test", "hunter2")
    assert out["role"] == "operator"
    assert captured["url"] == "https://pa.example/api/v1/auth/login"
    assert captured["data"] == {"username": "admin@acme.test", "password": "hunter2"}
