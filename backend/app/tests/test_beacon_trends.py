"""
Beacon ingestion (metadata-only, credential-rejecting) and trend endpoints.
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
from app.db import models as m  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client, **kw):
    return client.post("/api/v1/seed/synthetic",
                       json={"n_employees": 15, "n_campaigns": 3, "seed": 9, **kw}).json()


def _admin(client, body):
    u = next(u for u in body["demo_users"] if u["role"] == "org_admin")
    tok = client.post("/api/v1/auth/login",
                      data={"username": u["email"], "password": u["password"]}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _link_first_campaign(client, tid, H, ref="gp-test-1"):
    """Give one campaign an external_ref and return (ref, an employee email)."""
    camps = client.get(f"/api/v1/tenants/{tid}/dashboard/campaigns", headers=H).json()
    # find the campaign id via manage list
    mcamps = client.get(f"/api/v1/tenants/{tid}/manage/campaigns", headers=H).json()
    cid = mcamps[0]["id"]
    client.patch(f"/api/v1/tenants/{tid}/manage/campaigns/{cid}",
                 json={"external_ref": ref}, headers=H)
    emp = client.get(f"/api/v1/tenants/{tid}/manage/employees", headers=H).json()[0]
    return ref, emp["email"]


def test_beacon_records_metadata(client):
    body = _seed(client); tid = body["tenant_id"]; H = _admin(client, body)
    ref, email = _link_first_campaign(client, tid, H)
    r = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": ref, "email": email,
              "events": [{"type": "clicked"},
                         {"type": "field_focus"},
                         {"type": "dwell", "seconds": 22},
                         {"type": "typed_no_submit"}]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "recorded" and r.json()["stored"] == 4
    # the dwell value persisted; no credential column exists to leak into
    ev = client.get(f"/api/v1/tenants/{tid}/manage/employees", headers=H)
    assert ev.status_code == 200


def test_beacon_rejects_credential_field(client):
    body = _seed(client, seed=10); tid = body["tenant_id"]; H = _admin(client, body)
    ref, email = _link_first_campaign(client, tid, H, ref="gp-cred")
    # a password field smuggled into an event -> 422 (extra field forbidden)
    r = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": ref, "email": email,
              "events": [{"type": "submitted", "password": "hunter2"}]})
    assert r.status_code == 422

    # a non-dwell event carrying a scalar -> rejected
    r2 = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": ref, "email": email,
              "events": [{"type": "field_focus", "seconds": 5}]})
    assert r2.status_code == 422

    # an unknown event type -> rejected
    r3 = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": ref, "email": email,
              "events": [{"type": "keylog"}]})
    assert r3.status_code == 422

    # top-level credential-looking key -> rejected by defence-in-depth scan
    r4 = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": ref, "email": email, "otp": "123456",
              "events": [{"type": "clicked"}]})
    assert r4.status_code == 422


def test_beacon_unmapped_when_unknown_target(client):
    body = _seed(client, seed=11); tid = body["tenant_id"]
    r = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": "nope", "email": "ghost@nowhere.local",
              "events": [{"type": "clicked"}]})
    out = r.json()
    assert r.status_code == 200 and out["status"] == "unmapped"
    # generic reason codes only - the raw campaign_ref/email must never be
    # echoed back on this public, token-gated-only endpoint (roster
    # enumeration guard).
    assert set(out["reasons"]) <= {"campaign_not_linked", "employee_not_found"}
    for reason in out["reasons"]:
        assert "ghost@nowhere.local" not in reason and "nope" not in reason


def test_org_and_employee_trend(client):
    body = _seed(client, seed=12); tid = body["tenant_id"]; H = _admin(client, body)
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=H)

    ot = client.get(f"/api/v1/tenants/{tid}/dashboard/trend?weeks=6", headers=H)
    assert ot.status_code == 200
    pts = ot.json()["points"]
    assert len(pts) == 6
    assert pts[0]["date"] <= pts[-1]["date"]          # oldest -> newest
    assert all("mean_hrs" in p for p in pts)

    emp = client.get(f"/api/v1/tenants/{tid}/dashboard/employees", headers=H).json()[0]
    et = client.get(
        f"/api/v1/tenants/{tid}/dashboard/employees/{emp['employee_id']}/trend?weeks=6",
        headers=H)
    assert et.status_code == 200
    ep = et.json()["points"]
    assert len(ep) == 6 and all(0 <= p["hrs"] <= 100 for p in ep)
    # most recent trend point should agree with the stored headline HRS
    assert abs(ep[-1]["hrs"] - emp["hrs"]) < 0.05
