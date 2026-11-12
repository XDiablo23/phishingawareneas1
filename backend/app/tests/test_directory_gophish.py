"""
Tests for the two new operator integrations:
  * Entra (Azure AD) directory sync  - mocked Microsoft Graph
  * GoPhish full campaign lifecycle   - mocked GoPhish REST API

Both mock only the network boundary, so the real mapping, upsert, linking,
guardrail and RBAC logic is exercised.
"""
import json
import os

os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.db.base as base
base.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool, future=True)
base.SessionLocal.configure(bind=base.engine)

from app.main import app  # noqa: E402
from app.db.base import init_db  # noqa: E402
from app.integrations import entra as entra_mod  # noqa: E402
from app.integrations import gophish_admin as gpa_mod  # noqa: E402
from app.integrations import gophish_sync as gp_sync_mod  # noqa: E402
from app.integrations import ldap_dir as ldap_mod  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client, **kw):
    return client.post("/api/v1/seed/synthetic",
                       json={"n_employees": 12, "n_campaigns": 2, "seed": 3, **kw}).json()


def _tok(client, body, role):
    u = next(u for u in body["demo_users"] if u["role"] == role)
    return client.post("/api/v1/auth/login",
                       data={"username": u["email"], "password": u["password"]}).json()["access_token"]


def _A(t):
    return {"Authorization": f"Bearer {t}"}


# ---- fake Microsoft Graph users ----
FAKE_USERS = [
    {"displayName": "Ada Boss", "mail": "ada@acme.io", "department": "Executive",
     "jobTitle": "Chief Executive Officer", "officeLocation": "HQ"},
    {"displayName": "Ben Dir", "userPrincipalName": "ben@acme.io", "mail": None,
     "department": "Sales", "jobTitle": "Director of Sales", "officeLocation": "NY"},
    {"displayName": "Cy Staff", "mail": "cy@acme.io", "department": "IT",
     "jobTitle": "Analyst", "officeLocation": "Remote"},
    {"displayName": "No Email", "mail": None, "userPrincipalName": "",
     "department": "X", "jobTitle": "Ghost"},
]


# ---- fake GoPhish REST ----
def make_fake_gp():
    calls = {"groups": []}

    def fake_request(base_url, key, method, path, body=None, verify=True):
        if method == "GET" and path == "/api/templates/":
            return [{"id": 1, "name": "IT Password Reset"}]
        if method == "GET" and path == "/api/pages/":
            return [{"id": 1, "name": "Login Clone", "capture_credentials": True,
                     "capture_passwords": True},
                    {"id": 2, "name": "Safe Landing", "capture_credentials": False,
                     "capture_passwords": False}]
        if method == "GET" and path == "/api/smtp/":
            return [{"id": 1, "name": "Sim SMTP", "from_address": "it@acme.io"}]
        if method == "GET" and path == "/api/groups/":
            return calls["groups"]
        if method == "POST" and path == "/api/groups/":
            g = {"id": 99, "name": body["name"], "targets": body["targets"]}
            calls["groups"].append(g)
            calls["last_group"] = body
            return g
        if method == "PUT" and path.startswith("/api/groups/"):
            calls["last_group"] = body
            return {"id": body.get("id"), "name": body["name"]}
        if method == "POST" and path == "/api/campaigns/":
            calls["last_campaign"] = body
            return {"id": 1234, "name": body["name"], "status": "In progress"}
        if method == "GET" and path.endswith("/complete"):
            calls["completed"] = path
            return {"success": True}
        if method == "DELETE" and path.startswith("/api/campaigns/"):
            calls["deleted"] = path
            return {"success": True}
        return {}

    return fake_request, calls


def _fake_fetch(users):
    def f(tenant, limit=None):
        return users[:limit] if limit else users
    return f


# ================= Entra (Azure AD) directory =================
def test_entra_config_status_preview(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    # config is admin-only
    assert client.post(f"{m}/integration/entra/config", headers=_A(op),
                       json={"tenant_id": "t"}).status_code == 403
    r = client.post(f"{m}/integration/entra/config", headers=_A(admin),
                    json={"tenant_id": "contoso.onmicrosoft.com",
                          "client_id": "cid", "client_secret": "shh"})
    assert r.status_code == 200, r.text
    assert r.json()["client_secret_set"] is True

    monkeypatch.setattr(entra_mod, "fetch_users", _fake_fetch(FAKE_USERS))
    st = client.get(f"{m}/integration/entra/status", headers=_A(op)).json()
    assert st["ok"] is True and st["client_id_set"] is True

    prev = client.get(f"{m}/integration/entra/preview", headers=_A(op)).json()["users"]
    # 3 mapped (the no-email one is dropped), seniority derived, UPN email used
    emails = {u["email"] for u in prev}
    assert emails == {"ada@acme.io", "ben@acme.io", "cy@acme.io"}
    by_email = {u["email"]: u for u in prev}
    assert by_email["ada@acme.io"]["seniority_level"] == "Exec"
    assert by_email["ben@acme.io"]["seniority_level"] == "Director"
    assert by_email["cy@acme.io"]["seniority_level"] == "Staff"


def test_entra_sync_upserts_roster(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    monkeypatch.setattr(entra_mod, "fetch_users", _fake_fetch(FAKE_USERS))
    r = client.post(f"{m}/integration/entra/sync", headers=_A(op)).json()
    assert r["total"] == 4 and r["created"] == 3 and r["skipped"] == 1

    # the imported employee is in the roster with mapped fields
    roster = client.get(f"{m}/employees", headers=_A(op)).json()
    ada = next(e for e in roster if e["email"] == "ada@acme.io")
    assert ada["department"] == "Executive" and ada["seniority_level"] == "Exec"

    # second sync updates, never duplicates
    r2 = client.post(f"{m}/integration/entra/sync", headers=_A(op)).json()
    assert r2["created"] == 0 and r2["updated"] == 3
    roster2 = client.get(f"{m}/employees", headers=_A(op)).json()
    assert len([e for e in roster2 if e["email"] == "ada@acme.io"]) == 1


class _FakeGraphResponse:
    """Minimal stand-in for the object `urllib.request.urlopen` returns:
    usable as a context manager, `.read()` gives raw JSON bytes."""
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_entra_rejects_untrusted_nextlink(monkeypatch):
    """fetch_users() paginates by following Graph's own `@odata.nextLink`.
    If that URL ever points somewhere other than Microsoft's real hosts
    (malformed/compromised response, or a bug upstream), _http() must
    refuse to follow it rather than silently making the request."""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=25):
        calls["n"] += 1
        url = req.full_url
        if "login.microsoftonline.com" in url:
            return _FakeGraphResponse({"access_token": "faketoken"})
        if calls["n"] == 2:
            # First (legitimate) Graph page, but its nextLink points off
            # the allowed host - fetch_users must never follow it.
            return _FakeGraphResponse({
                "value": [{"id": "1", "displayName": "A", "mail": "a@acme.io"}],
                "@odata.nextLink": "https://evil.example/v1.0/users?$skiptoken=x",
            })
        raise AssertionError(
            "must never call urlopen against the untrusted nextLink host")

    monkeypatch.setattr(entra_mod.urllib.request, "urlopen", fake_urlopen)

    class _FakeTenant:
        entra_tenant_id = "tid"
        entra_client_id = "cid"
        entra_client_secret = "sec"

    with pytest.raises(entra_mod.EntraError):
        entra_mod.fetch_users(_FakeTenant())
    assert calls["n"] == 2  # stopped before a 3rd (malicious-host) request


# ================= GoPhish full lifecycle =================
def test_gophish_pickers_and_group_from_roster(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"
    fake, calls = make_fake_gp()
    monkeypatch.setattr(gpa_mod, "_request", fake)

    pages = client.get(f"{m}/integration/gophish/pages", headers=_A(op)).json()
    assert any(p["name"] == "Login Clone" and p["capture_passwords"] for p in pages)
    assert client.get(f"{m}/integration/gophish/templates", headers=_A(op)).json()[0]["name"] == "IT Password Reset"
    assert client.get(f"{m}/integration/gophish/smtp", headers=_A(op)).json()[0]["from_address"] == "it@acme.io"

    r = client.post(f"{m}/integration/gophish/groups/from-roster", headers=_A(op),
                    json={"name": "All Staff"})
    assert r.status_code == 200, r.text
    assert r.json()["targets"] == 12
    # targets were built from our roster (email present on each)
    assert all(t.get("email") for t in calls["last_group"]["targets"])


def test_gophish_launch_requires_authorization(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"
    fake, calls = make_fake_gp()
    monkeypatch.setattr(gpa_mod, "_request", fake)

    payload = {"name": "Q3 Test", "template": "IT Password Reset",
               "page": "Safe Landing", "smtp": "Sim SMTP", "group": "All Staff",
               "url": "http://sim.acme.io", "tier": 2,
               "attack_vector": "credential_harvest", "authorized": False}
    assert client.post(f"{m}/integration/gophish/campaigns/launch",
                       headers=_A(op), json=payload).status_code == 422
    assert "last_campaign" not in calls  # nothing was created


def test_gophish_launch_links_and_warns(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    viewer = _tok(client, body, "dept_viewer")
    m = f"/api/v1/tenants/{tid}/manage"
    fake, calls = make_fake_gp()
    monkeypatch.setattr(gpa_mod, "_request", fake)

    base_payload = {"name": "Q3 Finance", "template": "IT Password Reset",
                    "smtp": "Sim SMTP", "group": "All Staff",
                    "url": "http://sim.acme.io", "tier": 3,
                    "attack_vector": "credential_harvest", "authorized": True}

    # dept_viewer cannot launch
    assert client.post(f"{m}/integration/gophish/campaigns/launch", headers=_A(viewer),
                       json={**base_payload, "page": "Safe Landing"}).status_code == 403

    # launch against a password-capturing page -> warning + linked local campaign
    r = client.post(f"{m}/integration/gophish/campaigns/launch", headers=_A(op),
                    json={**base_payload, "page": "Login Clone"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["gophish_id"] == "1234" and out["local_campaign_id"]
    assert out["warning"] and "Capture Passwords" in out["warning"]
    assert calls["last_campaign"]["template"] == {"name": "IT Password Reset"}

    # the local campaign is linked by external_ref so scoring will pick it up
    camps = client.get(f"{m}/campaigns", headers=_A(op)).json()
    assert any(c.get("external_ref") == "1234" for c in camps)


def test_gophish_complete_and_delete_rbac(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    admin = _tok(client, body, "org_admin")
    m = f"/api/v1/tenants/{tid}/manage"
    fake, calls = make_fake_gp()
    monkeypatch.setattr(gpa_mod, "_request", fake)

    assert client.post(f"{m}/integration/gophish/campaigns/1234/complete",
                       headers=_A(op)).status_code == 200
    assert calls["completed"].endswith("/complete")
    # delete is admin-only
    assert client.delete(f"{m}/integration/gophish/campaigns/1234",
                         headers=_A(op)).status_code == 403
    assert client.delete(f"{m}/integration/gophish/campaigns/1234",
                         headers=_A(admin)).status_code == 200
    assert calls["deleted"].endswith("/1234")


def test_gophish_resolve_conn_verify_tls_per_tenant(monkeypatch):
    """Tenant.gophish_verify_tls must take precedence over the global
    GOPHISH_VERIFY_TLS setting; None must fall back to it - unit-level
    regression test for the per-tenant TLS override fix."""
    import app.config as config_mod
    from app.integrations import gophish_sync as gp_mod

    class _T:
        gophish_base_url = "https://gp.example"
        gophish_api_key = "k"
        gophish_verify_tls = None

    monkeypatch.setattr(config_mod.settings, "GOPHISH_VERIFY_TLS", True)
    assert gp_mod.resolve_conn(_T())[2] is True  # None -> inherits global default

    _T.gophish_verify_tls = False
    assert gp_mod.resolve_conn(_T())[2] is False  # tenant override wins

    monkeypatch.setattr(config_mod.settings, "GOPHISH_VERIFY_TLS", False)
    _T.gophish_verify_tls = True
    assert gp_mod.resolve_conn(_T())[2] is True  # override wins in the other direction too


def test_gophish_config_verify_tls_tri_state(client, monkeypatch):
    """The config endpoint's verify_tls field: omit to leave unchanged,
    true/false to set an override, explicit null to clear back to the
    server default."""
    monkeypatch.setattr(gp_sync_mod, "list_campaigns", lambda tenant: [])

    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    m = f"/api/v1/tenants/{tid}/manage"

    r = client.post(f"{m}/integration/gophish/config", headers=_A(admin),
                    json={"base_url": "https://gp.acme.io", "api_key": "k"})
    assert r.status_code == 200, r.text
    assert r.json()["verify_tls_override"] is None  # omitted -> unset

    r = client.post(f"{m}/integration/gophish/config", headers=_A(admin),
                    json={"verify_tls": True})
    assert r.json()["verify_tls_override"] is True and r.json()["verify_tls"] is True

    r = client.post(f"{m}/integration/gophish/config", headers=_A(admin),
                    json={"verify_tls": False})
    assert r.json()["verify_tls_override"] is False and r.json()["verify_tls"] is False

    r = client.post(f"{m}/integration/gophish/config", headers=_A(admin),
                    json={"verify_tls": None})
    assert r.json()["verify_tls_override"] is None  # explicit null clears it


# ================= LDAP (on-prem Active Directory) =================
FAKE_AD = [
    {"displayName": "Dana Exec", "mail": "dana@corp.local", "department": "Board",
     "title": "Chief Financial Officer", "physicalDeliveryOfficeName": "HQ"},
    {"displayName": "Eli Mgr", "userPrincipalName": "eli@corp.local", "mail": None,
     "department": "Ops", "title": "Operations Manager", "physicalDeliveryOfficeName": "Plant"},
    {"displayName": "Fay Staff", "mail": "fay@corp.local", "department": "Support",
     "title": "Agent", "physicalDeliveryOfficeName": None},
    {"displayName": "No Mail", "mail": None, "userPrincipalName": None,
     "department": "X", "title": "Ghost"},
]


def test_ldap_config_status_preview(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    op = _tok(client, body, "operator")
    mm = f"/api/v1/tenants/{tid}/manage"

    # config is admin-only
    assert client.post(f"{mm}/integration/ldap/config", headers=_A(op),
                       json={"uri": "ldap://x"}).status_code == 403
    r = client.post(f"{mm}/integration/ldap/config", headers=_A(admin),
                    json={"uri": "ldap://dc.corp.local:389", "bind_dn": "svc@corp.local",
                          "bind_password": "shh", "base_dn": "DC=corp,DC=local"})
    assert r.status_code == 200, r.text
    assert r.json()["bind_password_set"] is True

    monkeypatch.setattr(ldap_mod, "fetch_users", _fake_fetch(FAKE_AD))
    st = client.get(f"{mm}/integration/ldap/status", headers=_A(op)).json()
    assert st["ok"] is True and st["ldap_base_dn"] == "DC=corp,DC=local"

    prev = client.get(f"{mm}/integration/ldap/preview", headers=_A(op)).json()["users"]
    by_email = {u["email"]: u for u in prev}
    assert set(by_email) == {"dana@corp.local", "eli@corp.local", "fay@corp.local"}
    assert by_email["dana@corp.local"]["seniority_level"] == "Exec"
    assert by_email["eli@corp.local"]["seniority_level"] == "Manager"
    assert by_email["fay@corp.local"]["seniority_level"] == "Staff"


def test_ldap_sync_upserts_roster(client, monkeypatch):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    mm = f"/api/v1/tenants/{tid}/manage"

    monkeypatch.setattr(ldap_mod, "fetch_users", _fake_fetch(FAKE_AD))
    r = client.post(f"{mm}/integration/ldap/sync", headers=_A(op)).json()
    assert r["total"] == 4 and r["created"] == 3 and r["skipped"] == 1

    roster = client.get(f"{mm}/employees", headers=_A(op)).json()
    dana = next(e for e in roster if e["email"] == "dana@corp.local")
    assert dana["department"] == "Board" and dana["seniority_level"] == "Exec"

    r2 = client.post(f"{mm}/integration/ldap/sync", headers=_A(op)).json()
    assert r2["created"] == 0 and r2["updated"] == 3
