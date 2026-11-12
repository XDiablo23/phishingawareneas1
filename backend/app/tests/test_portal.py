"""
Portal API tests: the read/write surface the separate Awareness &
Remediation Portal uses to sync over REST.

Covers: reading employee signals, find-or-create by email, the baseline
risk-floor (raises but never lowers HRS; surfaces in the console), the
in-person awareness mark (set/clear + stamped since), and the per-tenant
service-token auth that gates this whole router (X-Portal-Token) - a
narrowly-scoped replacement for the full operator/admin JWT this surface
used to accept.
"""

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


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client, **kw):
    return client.post("/api/v1/seed/synthetic",
                       json={"n_employees": 15, "n_campaigns": 3, "seed": 7, **kw}).json()


def _tok(client, body, role):
    u = next(u for u in body["demo_users"] if u["role"] == role)
    return client.post("/api/v1/auth/login",
                       data={"username": u["email"], "password": u["password"]}).json()["access_token"]


def _A(t):
    return {"Authorization": f"Bearer {t}"}


def _portal_token(client, tid, admin_tok):
    """Rotate (generate) this tenant's portal service token via the real
    admin-only endpoint, the same way an operator would from the console."""
    r = client.post(f"/api/v1/tenants/{tid}/manage/integration/rotate",
                    headers=_A(admin_tok), json={"field": "portal_service_token"})
    assert r.status_code == 200, r.text
    return r.json()["value"]


def _PT(token):
    return {"X-Portal-Token": token}


def test_portal_requires_service_token(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    p = f"/api/v1/tenants/{tid}/portal"

    # no token at all -> 401
    assert client.get(f"{p}/employees").status_code == 401
    # an operator/admin JWT is no longer accepted here - it's not what this
    # surface authenticates with anymore
    op = _tok(client, body, "operator")
    assert client.get(f"{p}/employees", headers=_A(op)).status_code == 401

    tok = _portal_token(client, tid, admin)
    assert client.get(f"{p}/employees", headers=_PT(tok)).status_code == 200

    # wrong token -> 401
    assert client.get(f"{p}/employees", headers=_PT(tok + "x")).status_code == 401

    # a token belonging to a DIFFERENT tenant must not work here
    body2 = _seed(client, seed=99)
    tid2 = body2["tenant_id"]
    admin2 = _tok(client, body2, "org_admin")
    other_tok = _portal_token(client, tid2, admin2)
    assert client.get(f"{p}/employees", headers=_PT(other_tok)).status_code == 401

    # rotating invalidates the old value immediately
    new_tok = _portal_token(client, tid, admin)
    assert new_tok != tok
    assert client.get(f"{p}/employees", headers=_PT(tok)).status_code == 401
    assert client.get(f"{p}/employees", headers=_PT(new_tok)).status_code == 200


def test_portal_list_and_by_email(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"

    r = client.get(f"{p}/employees", headers=_PT(tok))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 1
    # signal shape
    row = rows[0]
    for k in ("employee_id", "email", "hrs", "hrs_band",
              "risk_floor", "needs_inperson_awareness"):
        assert k in row, k

    # by-email round-trips
    r2 = client.get(f"{p}/employees/by-email",
                    headers=_PT(tok), params={"email": row["email"]})
    assert r2.status_code == 200
    assert r2.json()["employee_id"] == row["employee_id"]

    # unknown email -> 404
    assert client.get(f"{p}/employees/by-email", headers=_PT(tok),
                      params={"email": "nobody@nowhere.test"}).status_code == 404


def test_portal_ensure_is_idempotent(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"

    payload = {"email": "newhire@acme.test", "full_name": "New Hire",
               "department": "Sales", "job_title": "Rep",
               "seniority_level": "Staff"}
    r = client.post(f"{p}/employees/ensure", headers=_PT(tok), json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    eid = r.json()["employee_id"]
    # fresh record: no events yet
    assert r.json()["hrs"] == 0.0
    assert r.json()["hrs_band"] == "Low"

    # second call finds the same record
    r2 = client.post(f"{p}/employees/ensure", headers=_PT(tok), json=payload)
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    assert r2.json()["employee_id"] == eid


def test_risk_floor_raises_then_shows_in_console(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"
    d = f"/api/v1/tenants/{tid}/dashboard"

    # a fresh (zero-score) employee via ensure
    eid = client.post(f"{p}/employees/ensure", headers=_PT(tok),
                      json={"email": "floor@acme.test", "full_name": "Floor Test",
                            "department": "Ops", "job_title": "Analyst"}).json()["employee_id"]

    # push a Moderate baseline (35)
    r = client.post(f"{p}/employees/{eid}/risk-floor", headers=_PT(tok),
                    json={"value": 35})
    assert r.status_code == 200, r.text
    assert r.json()["hrs"] == 35.0
    assert r.json()["hrs_band"] == "Moderate"

    # visible in the operator console (dashboard) without a manual recompute
    det = client.get(f"{d}/employees/{eid}", headers=_A(admin)).json()
    assert det["hrs"] == 35.0 and det["hrs_band"] == "Moderate"
    assert det["risk_floor"] == 35.0

    # clearing the floor drops the fresh employee back to 0/Low
    r = client.post(f"{p}/employees/{eid}/risk-floor", headers=_PT(tok),
                    json={"value": None})
    assert r.status_code == 200
    assert r.json()["hrs"] == 0.0 and r.json()["hrs_band"] == "Low"
    assert r.json()["risk_floor"] is None


def test_risk_floor_never_lowers(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=_A(admin))

    # pick the highest-scoring real employee
    rows = client.get(f"{p}/employees", headers=_PT(tok)).json()
    top = max(rows, key=lambda x: x["hrs"])
    assert top["hrs"] > 10, "seed should produce at least one non-trivial score"

    before = top["hrs"]
    r = client.post(f"{p}/employees/{top['employee_id']}/risk-floor",
                    headers=_PT(tok), json={"value": 10})
    assert r.status_code == 200
    # floor below current score must not lower it
    assert r.json()["hrs"] == before
    assert r.json()["risk_floor"] == 10.0


def test_inperson_flag_set_clear_and_surfaces(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"
    d = f"/api/v1/tenants/{tid}/dashboard"

    # a scored employee (the real case for someone stuck High/Critical):
    # recompute so the console list is populated, then flag one of them.
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=_A(admin))
    eid = client.get(f"{d}/employees", headers=_A(admin)).json()[0]["employee_id"]

    # raise the mark
    r = client.post(f"{p}/employees/{eid}/inperson-flag", headers=_PT(tok),
                    json={"on": True, "reason": "Stuck Critical for 45 days"})
    assert r.status_code == 200, r.text
    sig = r.json()
    assert sig["needs_inperson_awareness"] is True
    assert sig["inperson_reason"] == "Stuck Critical for 45 days"
    assert sig["inperson_since"] is not None

    # surfaces in the console list + detail
    lst = client.get(f"{d}/employees", headers=_A(admin)).json()
    assert any(e["employee_id"] == eid and e["needs_inperson_awareness"]
               for e in lst)
    det = client.get(f"{d}/employees/{eid}", headers=_A(admin)).json()
    assert det["needs_inperson_awareness"] is True
    assert det["inperson_reason"] == "Stuck Critical for 45 days"

    # clear the mark
    r = client.post(f"{p}/employees/{eid}/inperson-flag", headers=_PT(tok),
                    json={"on": False})
    assert r.status_code == 200
    assert r.json()["needs_inperson_awareness"] is False
    assert r.json()["inperson_reason"] is None
    assert r.json()["inperson_since"] is None


def test_portal_writes_audited_as_service_actor(client):
    """AuditLog.actor for portal-originated writes should be the fixed
    machine identity, not a human user email - there is no human in this
    call path any more."""
    from app.db import models as m

    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    tok = _portal_token(client, tid, admin)
    p = f"/api/v1/tenants/{tid}/portal"

    eid = client.post(f"{p}/employees/ensure", headers=_PT(tok),
                      json={"email": "svc-actor@acme.test", "full_name": "Svc Actor",
                            "department": "Ops", "job_title": "Analyst"}).json()["employee_id"]
    client.post(f"{p}/employees/{eid}/risk-floor", headers=_PT(tok), json={"value": 20})

    s = base.SessionLocal()
    try:
        entry = (s.query(m.AuditLog)
                 .filter_by(tenant_id=tid, action="portal_set_risk_floor")
                 .order_by(m.AuditLog.created_at.desc()).first())
        assert entry is not None
        assert entry.actor == "portal-service"
    finally:
        s.close()
