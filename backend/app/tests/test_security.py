"""
Security regression tests: response headers, JWT expiry enforcement, and CSV
formula-injection escaping on export.
"""
import os

os.environ["DATABASE_URL"] = "sqlite://"

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.db.base as base
base.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool, future=True)
base.SessionLocal.configure(bind=base.engine)

from app.main import app          # noqa: E402
from app.db.base import init_db   # noqa: E402
from app.config import settings   # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client):
    return client.post("/api/v1/seed/synthetic",
                       json={"n_employees": 4, "n_campaigns": 1, "seed": 5}).json()


def _tok(client, body, role):
    u = next(u for u in body["demo_users"] if u["role"] == role)
    return client.post("/api/v1/auth/login",
                       data={"username": u["email"], "password": u["password"]}).json()["access_token"]


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert "default-src 'none'" in (r.headers.get("Content-Security-Policy") or "")
    assert r.headers.get("Cache-Control") == "no-store"


def test_jwt_without_exp_is_rejected(client):
    # a token signed with the right key but no exp must be refused
    forged = jwt.encode({"sub": "x", "role": "org_admin", "tenant_id": "t"},
                        settings.SECRET_KEY, algorithm="HS256")
    r = client.get("/api/v1/tenants/t/manage/employees",
                   headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_jwt_wrong_key_is_rejected(client):
    forged = jwt.encode({"sub": "x", "role": "org_admin", "exp": 9999999999},
                        "not-the-real-key", algorithm="HS256")
    r = client.get("/api/v1/tenants/t/manage/employees",
                   headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_login_sets_session_and_csrf_cookies(client):
    client.cookies.clear()
    body = _seed(client)
    email, pw = next((u["email"], u["password"]) for u in body["demo_users"]
                     if u["role"] == "org_admin")
    r = client.post("/api/v1/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200
    assert "access_token" in r.cookies and "csrf_token" in r.cookies
    # the JSON body still carries the bearer token too (API/script clients)
    assert r.json()["access_token"]
    client.cookies.clear()


def test_cookie_samesite_switches_with_environment(monkeypatch):
    # Lax cookies are never attached to a cross-site fetch/XHR at all, which
    # would silently break the documented split-origin deployment
    # (VITE_API_BASE on a separate origin) despite the CORS grant - so
    # production must use None (paired with Secure), while local dev (same
    # origin via the Vite proxy, no HTTPS) stays Lax.
    from fastapi import Response

    from app.api.security import set_auth_cookies

    monkeypatch.setattr(settings, "ENV", "production")
    prod_resp = Response()
    set_auth_cookies(prod_resp, "tok")
    prod_cookies = [v.decode() for k, v in prod_resp.raw_headers if k == b"set-cookie"]
    assert len(prod_cookies) == 2
    assert all("samesite=none" in c.lower() for c in prod_cookies)
    assert all("secure" in c.lower() for c in prod_cookies)

    monkeypatch.setattr(settings, "ENV", "development")
    dev_resp = Response()
    set_auth_cookies(dev_resp, "tok")
    dev_cookies = [v.decode() for k, v in dev_resp.raw_headers if k == b"set-cookie"]
    assert len(dev_cookies) == 2
    assert all("samesite=lax" in c.lower() for c in dev_cookies)
    assert not any("secure" in c.lower() for c in dev_cookies)


def test_cookie_alone_authenticates_a_get(client):
    client.cookies.clear()
    body = _seed(client)
    tid = body["tenant_id"]
    email, pw = next((u["email"], u["password"]) for u in body["demo_users"]
                     if u["role"] == "operator")
    client.post("/api/v1/auth/login", data={"username": email, "password": pw})
    # no Authorization header at all - only the cookie set by login above
    r = client.get(f"/api/v1/tenants/{tid}/dashboard/summary")
    assert r.status_code == 200
    client.cookies.clear()


def test_csrf_required_for_cookie_authenticated_mutation(client):
    client.cookies.clear()
    body = _seed(client)
    tid = body["tenant_id"]
    email, pw = next((u["email"], u["password"]) for u in body["demo_users"]
                     if u["role"] == "operator")
    client.post("/api/v1/auth/login", data={"username": email, "password": pw})

    # cookie-authenticated POST with no CSRF header -> rejected
    r = client.post(f"/api/v1/tenants/{tid}/recompute")
    assert r.status_code == 403
    assert "csrf" in r.json()["detail"].lower()

    # same request with the matching CSRF header -> succeeds
    csrf = client.cookies.get("csrf_token")
    r2 = client.post(f"/api/v1/tenants/{tid}/recompute",
                     headers={"X-CSRF-Token": csrf})
    assert r2.status_code == 200
    client.cookies.clear()


def test_csrf_not_required_for_bearer_header_mutation(client):
    """A request carrying its own Authorization header is never subject to
    the CSRF check - that's the API/script client path."""
    client.cookies.clear()
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    client.cookies.clear()  # login above also set cookies; drop them
    r = client.post(f"/api/v1/tenants/{tid}/recompute",
                    headers={"Authorization": f"Bearer {admin}"})
    assert r.status_code == 200


def test_logout_clears_session_cookies(client):
    client.cookies.clear()
    body = _seed(client)
    tid = body["tenant_id"]
    email, pw = next((u["email"], u["password"]) for u in body["demo_users"]
                     if u["role"] == "operator")
    client.post("/api/v1/auth/login", data={"username": email, "password": pw})
    assert client.get(f"/api/v1/tenants/{tid}/dashboard/summary").status_code == 200

    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 200
    # httpx's client applies the Set-Cookie deletions to its own jar exactly
    # like a real browser would; a follow-up request with nothing else
    # attached must now be unauthenticated
    assert client.get(f"/api/v1/tenants/{tid}/dashboard/summary").status_code == 401
    client.cookies.clear()


def test_csv_export_escapes_formula(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    H = {"Authorization": f"Bearer {admin}"}
    # an employee whose name is a spreadsheet formula
    client.post(f"/api/v1/tenants/{tid}/manage/employees", headers=H,
                json={"full_name": "=HYPERLINK(\"http://evil\")", "email": "x@e.io",
                      "department": "IT", "job_title": "Analyst"})
    csv_text = client.get(f"/api/v1/tenants/{tid}/manage/export/employees.csv",
                          headers=H).text
    # the dangerous cell is neutralised with a leading quote, never raw "=HYPER"
    assert "'=HYPERLINK" in csv_text
    assert "\n=HYPERLINK" not in csv_text and ",=HYPERLINK" not in csv_text
