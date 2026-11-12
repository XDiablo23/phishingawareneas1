"""
API integration tests (Stages 3-4), against in-memory SQLite so the whole
HTTP path is exercised: seed -> login -> ingest -> recompute -> read, plus
the credential-rejection guardrail and auth gating.
"""

import io
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
from app.db import models as m  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client, **kw):
    r = client.post("/api/v1/seed/synthetic", json=kw)
    assert r.status_code == 200
    return r.json()


def _creds(body, role):
    u = next(u for u in body["demo_users"] if u["role"] == role)
    return u["email"], u["password"]


def _token(client, email, password):
    r = client.post("/api/v1/auth/login",
                    data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_seed_creates_demo_users(client):
    body = _seed(client, n_employees=40, n_campaigns=6, seed=7)
    assert body["employees"] == 40 and body["events"] > 0
    roles = {u["role"] for u in body["demo_users"]}
    assert {"org_admin", "operator", "dept_viewer"} <= roles


def test_full_flow_with_auth(client):
    body = _seed(client, n_employees=40, n_campaigns=6, seed=11)
    tid = body["tenant_id"]
    oe, op = _creds(body, "operator"); tok = _token(client, oe, op)

    r = client.post(f"/api/v1/tenants/{tid}/recompute", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["employees_scored"] == 40

    r = client.get(f"/api/v1/tenants/{tid}/dashboard/employees", headers=_auth(tok))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 40
    hrs = [x["hrs"] for x in rows]
    assert hrs == sorted(hrs, reverse=True)  # default sort is the HRS column
    for x in rows:
        assert 0 <= x["hrs"] <= 100
        assert x["hrs_band"] in {"Low", "Moderate", "High", "Critical"}

    r = client.get(f"/api/v1/tenants/{tid}/dashboard/summary", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["employees"] == 40
    r = client.get(f"/api/v1/tenants/{tid}/dashboard/departments", headers=_auth(tok))
    assert r.status_code == 200 and isinstance(r.json(), list)
    r = client.get(f"/api/v1/tenants/{tid}/dashboard/campaigns", headers=_auth(tok))
    assert r.status_code == 200 and len(r.json()) == 6

    eid = rows[0]["employee_id"]
    r = client.get(f"/api/v1/tenants/{tid}/dashboard/employees/{eid}", headers=_auth(tok))
    assert r.status_code == 200 and "campaigns" in r.json()


def test_auth_required_and_role_enforced(client):
    # an earlier test in this module may have logged in on this same shared
    # TestClient, leaving a session cookie attached - clear it so "no
    # Authorization header" actually means "unauthenticated" below (in the
    # real app this is correct: once logged in, the cookie legitimately
    # authenticates header-less requests too).
    client.cookies.clear()
    body = _seed(client, n_employees=10, n_campaigns=2, seed=5)
    tid = body["tenant_id"]
    assert client.post(f"/api/v1/tenants/{tid}/recompute").status_code == 401
    assert client.get(f"/api/v1/tenants/{tid}/dashboard/summary").status_code == 401
    ve, vp = _creds(body, "dept_viewer"); vtok = _token(client, ve, vp)
    assert client.post(f"/api/v1/tenants/{tid}/recompute",
                       headers=_auth(vtok)).status_code == 403


def test_dept_viewer_scoping(client):
    body = _seed(client, n_employees=60, n_campaigns=5, seed=9)
    tid = body["tenant_id"]
    oe, op = _creds(body, "operator")
    otok = _token(client, oe, op)
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=_auth(otok))

    all_rows = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                          headers=_auth(otok)).json()
    assert len({x["department"] for x in all_rows}) > 1

    ve, vp = _creds(body, "dept_viewer"); vtok = _token(client, ve, vp)
    v_rows = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                        headers=_auth(vtok)).json()
    assert v_rows
    assert {x["department"] for x in v_rows} == {"Finance"}

    v_sum = client.get(f"/api/v1/tenants/{tid}/dashboard/summary",
                       headers=_auth(vtok)).json()
    assert v_sum["scope"]["department"] == "Finance"
    assert v_sum["employees"] == len(v_rows)


def test_credential_fields_rejected(client):
    body = _seed(client, n_employees=3, n_campaigns=1, seed=1)
    tid = body["tenant_id"]
    oe, op = _creds(body, "operator"); tok = _token(client, oe, op)
    bad = {"events": [{
        "campaign_id": "c", "employee_id": "e", "event_type": "submitted",
        "event_metadata": {"password": "hunter2"},
    }]}
    r = client.post(f"/api/v1/tenants/{tid}/events", json=bad, headers=_auth(tok))
    assert r.status_code == 422


def test_ingest_events_audit_records_caller(client):
    """AuditLog.actor must be the authenticated caller, not a hardcoded
    'api' placeholder - the real caller is recorded."""
    body = _seed(client, n_employees=3, n_campaigns=1, seed=13)
    tid = body["tenant_id"]
    oe, op = _creds(body, "operator")
    tok = _token(client, oe, op)

    s = base.SessionLocal()
    try:
        camp = s.query(m.Campaign).filter_by(tenant_id=tid).first()
        emp = s.query(m.Employee).filter_by(tenant_id=tid).first()
        camp_id, emp_id = camp.id, emp.id
    finally:
        s.close()

    r = client.post(f"/api/v1/tenants/{tid}/events",
                    json={"events": [{"campaign_id": camp_id,
                                       "employee_id": emp_id,
                                       "event_type": "clicked"}]},
                    headers=_auth(tok))
    assert r.status_code == 200 and r.json()["ingested"] == 1

    s = base.SessionLocal()
    try:
        entry = (s.query(m.AuditLog)
                 .filter_by(tenant_id=tid, action="ingest_events")
                 .order_by(m.AuditLog.created_at.desc()).first())
        assert entry is not None
        assert entry.actor == oe
        assert entry.actor != "api"
    finally:
        s.close()


def test_csv_ingest_rejects_credential_columns(client):
    body = _seed(client, n_employees=3, n_campaigns=1, seed=2)
    tid = body["tenant_id"]
    oe, op = _creds(body, "operator"); tok = _token(client, oe, op)
    csv_bad = "campaign_id,employee_id,event_type,password\nc,e,clicked,hunter2\n"
    r = client.post(f"/api/v1/tenants/{tid}/events/csv",
                    files={"file": ("e.csv", io.BytesIO(csv_bad.encode()), "text/csv")},
                    headers=_auth(tok))
    assert r.status_code == 400
    # use REAL ids for this tenant (events referencing unknown campaign/
    # employee ids are now rejected as a cross-tenant integrity guard)
    cid = client.get(f"/api/v1/tenants/{tid}/manage/campaigns", headers=_auth(tok)).json()[0]["id"]
    eid = client.get(f"/api/v1/tenants/{tid}/manage/employees", headers=_auth(tok)).json()[0]["id"]
    csv_ok = ("campaign_id,employee_id,event_type,value,breached\n"
              f"{cid},{eid},clicked,,\n"
              f"{cid},{eid},dwell,42,\n")
    r = client.post(f"/api/v1/tenants/{tid}/events/csv",
                    files={"file": ("e.csv", io.BytesIO(csv_ok.encode()), "text/csv")},
                    headers=_auth(tok))
    assert r.status_code == 200 and r.json()["ingested"] == 2
    # events referencing an unknown campaign/employee are rejected, not stored
    csv_bad_ids = ("campaign_id,employee_id,event_type\n"
                   "no-such-campaign,no-such-emp,clicked\n")
    r = client.post(f"/api/v1/tenants/{tid}/events/csv",
                    files={"file": ("e.csv", io.BytesIO(csv_bad_ids.encode()), "text/csv")},
                    headers=_auth(tok))
    assert r.status_code == 200 and r.json()["ingested"] == 0 and r.json()["rejected"] == 1


def test_employees_filters_and_sorting(client):
    body = _seed(client, n_employees=30, n_campaigns=5, seed=21)
    tid = body["tenant_id"]
    ae, ap = _creds(body, "org_admin"); H = _auth(_token(client, ae, ap))
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=H)

    # default: sorted by HRS desc (matches the column users read)
    rows = client.get(f"/api/v1/tenants/{tid}/dashboard/employees", headers=H).json()
    hrs = [r["hrs"] for r in rows]
    assert rows and hrs == sorted(hrs, reverse=True)

    # explicit sort + order
    asc = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                     params={"sort": "name", "order": "asc"}, headers=H).json()
    names = [r["full_name"].lower() for r in asc]
    assert names == sorted(names)

    # seniority filter
    sen = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                     params={"seniority": "Staff"}, headers=H).json()
    assert sen and all(r["seniority_level"] == "Staff" for r in sen)

    # q matches name or job title
    probe = rows[0]["full_name"].split()[0].lower()
    qres = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                      params={"q": probe}, headers=H).json()
    assert qres and all(
        probe in r["full_name"].lower() or probe in (r["job_title"] or "").lower()
        for r in qres)

    # invalid sort key -> 422
    bad = client.get(f"/api/v1/tenants/{tid}/dashboard/employees",
                     params={"sort": "nope"}, headers=H)
    assert bad.status_code == 422
