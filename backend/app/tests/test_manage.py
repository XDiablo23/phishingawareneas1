"""
Management-layer tests: campaign/roster/user CRUD, CSV import,
CSV export, RBAC gating, and the configurable HRS aggregation modes.
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


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client, **kw):
    return client.post("/api/v1/seed/synthetic",
                       json={"n_employees": 20, "n_campaigns": 3, "seed": 5, **kw}).json()


def _tok(client, body, role):
    u = next(u for u in body["demo_users"] if u["role"] == role)
    return client.post("/api/v1/auth/login",
                       data={"username": u["email"], "password": u["password"]}).json()["access_token"]


def _A(t):
    return {"Authorization": f"Bearer {t}"}


# ---- campaigns ----
def test_campaign_crud(client):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    r = client.post(f"{m}/campaigns", headers=_A(op),
                    json={"name": "Q1 Finance Test", "tier": 2, "attack_vector": "credential_harvest"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["status"] == "draft"

    # invalid tier rejected
    assert client.post(f"{m}/campaigns", headers=_A(op),
                       json={"name": "x", "tier": 9, "attack_vector": "chatbot"}).status_code == 422

    # list
    r = client.get(f"{m}/campaigns", headers=_A(op))
    assert any(c["id"] == cid for c in r.json())

    # update
    r = client.patch(f"{m}/campaigns/{cid}", headers=_A(op),
                     json={"status": "running", "external_ref": "gp-55"})
    assert r.status_code == 200 and r.json()["status"] == "running" and r.json()["external_ref"] == "gp-55"

    # delete
    assert client.delete(f"{m}/campaigns/{cid}", headers=_A(op)).status_code == 200
    assert all(c["id"] != cid for c in client.get(f"{m}/campaigns", headers=_A(op)).json())


def test_campaign_requires_manage_role(client):
    body = _seed(client)
    tid = body["tenant_id"]
    vt = _tok(client, body, "dept_viewer")
    r = client.post(f"/api/v1/tenants/{tid}/manage/campaigns", headers=_A(vt),
                    json={"name": "x", "tier": 1, "attack_vector": "link_only"})
    assert r.status_code == 403


# ---- roster ----
def test_employee_crud_and_conflict(client):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    r = client.post(f"{m}/employees", headers=_A(op),
                    json={"full_name": "New Person", "email": "new.person@corp.example",
                          "department": "Finance", "job_title": "Analyst",
                          "seniority_level": "Manager"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    # duplicate email -> 409
    assert client.post(f"{m}/employees", headers=_A(op),
                       json={"full_name": "Dup", "email": "new.person@corp.example",
                             "department": "HR", "job_title": "x"}).status_code == 409

    # invalid seniority -> 422
    assert client.post(f"{m}/employees", headers=_A(op),
                       json={"full_name": "Y", "email": "y@corp.example",
                             "department": "HR", "job_title": "x",
                             "seniority_level": "Overlord"}).status_code == 422

    # update
    r = client.patch(f"{m}/employees/{eid}", headers=_A(op),
                     json={"department": "IT", "seniority_level": "Director"})
    assert r.status_code == 200 and r.json()["department"] == "IT"

    # delete
    assert client.delete(f"{m}/employees/{eid}", headers=_A(op)).status_code == 200


def test_roster_csv_import(client):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    good = ("full_name,email,department,job_title,manager_email,seniority_level\n"
            "Aisha Khan,aisha@corp.example,Finance,Controller,,Manager\n"
            "Ben Ali,ben@corp.example,IT,Engineer,aisha@corp.example,Staff\n"
            "Bad Row,,Finance,Analyst,,Staff\n")  # missing email -> skipped
    r = client.post(f"{m}/employees/import", headers=_A(op),
                    files={"file": ("roster.csv", good.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 2 and res["skipped"] == 1

    # re-import updates existing (matched by email)
    again = ("full_name,email,department,job_title\n"
             "Aisha Khan,aisha@corp.example,Legal,Head of Legal\n")
    r = client.post(f"{m}/employees/import", headers=_A(op),
                    files={"file": ("roster.csv", again.encode(), "text/csv")})
    assert r.json()["updated"] == 1

    # credential column rejected
    bad = "full_name,email,department,job_title,password\nX,x@c.co,IT,Eng,secret\n"
    assert client.post(f"{m}/employees/import", headers=_A(op),
                       files={"file": ("r.csv", bad.encode(), "text/csv")}).status_code == 400


def test_roster_csv_import_enforces_length_caps(client):
    """A CSV row must be held to the same EmployeeCreate.full_name
    max_length=200 the manual add-employee endpoint enforces, not silently
    accepted past the DB column limit - regression test for the CSV
    validation fix."""
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    too_long_name = "N" * 201
    csv_body = ("full_name,email,department,job_title\n"
                f"{too_long_name},toolong@corp.example,IT,Engineer\n"
                "Fine Person,fine@corp.example,IT,Engineer\n")
    r = client.post(f"{m}/employees/import", headers=_A(op),
                    files={"file": ("roster.csv", csv_body.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 1 and res["skipped"] == 1
    assert "full_name" in res["errors"][0]

    roster = client.get(f"{m}/employees", headers=_A(op)).json()
    assert not any(e["email"] == "toolong@corp.example" for e in roster)
    assert any(e["email"] == "fine@corp.example" for e in roster)


# ---- users ----
def test_user_management(client):
    body = _seed(client)
    tid = body["tenant_id"]
    admin = _tok(client, body, "org_admin")
    op = _tok(client, body, "operator")
    m = f"/api/v1/tenants/{tid}/manage"

    # operator cannot manage users
    assert client.get(f"{m}/users", headers=_A(op)).status_code == 403

    # admin creates a user; gets a one-time password back
    r = client.post(f"{m}/users", headers=_A(admin),
                    json={"email": "newop@corp.example", "role": "operator"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw = r.json()["initial_password"]
    assert pw

    # the new user can actually log in with it
    assert client.post("/api/v1/auth/login",
                       data={"username": "newop@corp.example", "password": pw}).status_code == 200

    # dept_viewer without scope -> 422
    assert client.post(f"{m}/users", headers=_A(admin),
                       json={"email": "v@corp.example", "role": "dept_viewer"}).status_code == 422

    # cannot create super_admin
    assert client.post(f"{m}/users", headers=_A(admin),
                       json={"email": "sa@corp.example", "role": "super_admin"}).status_code == 403

    # reset password issues a new one that works
    r = client.post(f"{m}/users/{uid}/reset-password", headers=_A(admin))
    newpw = r.json()["initial_password"]
    assert client.post("/api/v1/auth/login",
                       data={"username": "newop@corp.example", "password": newpw}).status_code == 200

    # change role
    r = client.patch(f"{m}/users/{uid}", headers=_A(admin), json={"role": "dept_viewer", "department_scope": "IT"})
    assert r.status_code == 200 and r.json()["role"] == "dept_viewer"

    # delete
    assert client.delete(f"{m}/users/{uid}", headers=_A(admin)).status_code == 200


# ---- export ----
def test_csv_export_scoped(client):
    body = _seed(client)
    tid = body["tenant_id"]
    op = _tok(client, body, "operator")
    vt = _tok(client, body, "dept_viewer")
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=_A(op))

    r = client.get(f"/api/v1/tenants/{tid}/manage/export/employees.csv", headers=_A(op))
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    op_lines = [l for l in r.text.splitlines() if l.strip()]

    r = client.get(f"/api/v1/tenants/{tid}/manage/export/employees.csv", headers=_A(vt))
    v_lines = [l for l in r.text.splitlines() if l.strip()]
    # departmental viewer's export is scoped (fewer or equal rows), Finance only
    assert len(v_lines) <= len(op_lines)
    for row in v_lines[1:]:
        assert ",Finance," in row


# ---- aggregation modes ----
def test_aggregation_modes_change_hrs():
    from datetime import datetime, timezone
    from app.scoring import Event, CampaignContext, score_campaign, score_employee
    now = datetime(2027, 1, 15, tzinfo=timezone.utc)

    def ctx(days, cid):
        return CampaignContext(campaign_id=cid, tier=1, vector="credential_harvest",
                               campaign_date=now.replace() )

    # one severe recent failure + several ignored campaigns -> average dilutes, peak keeps it high
    severe = score_campaign([Event("clicked"), Event("dwell", value=30),
                             Event("field_focus"), Event("submitted")],
                            CampaignContext("a", 1, "credential_harvest", now))
    ignored = [score_campaign([Event("opened")],
                              CampaignContext(f"i{i}", 1, "credential_harvest", now))
               for i in range(4)]
    cs = [severe] + ignored
    avg = score_employee(cs, "Staff", as_of=now, aggregation="average")
    peak = score_employee(cs, "Staff", as_of=now, aggregation="peak")
    blend = score_employee(cs, "Staff", as_of=now, aggregation="blend", blend_alpha=0.5)
    assert peak.hrs > avg.hrs
    assert avg.hrs <= blend.hrs <= peak.hrs


# ---- integration config + secret rotation ----
def test_integration_config_and_rotation(client):
    body = _seed(client, seed=31)
    tid = body["tenant_id"]
    admin = _A(_tok(client, body, "org_admin"))
    op = _A(_tok(client, body, "operator"))

    # read: URLs present, secrets not yet set, no raw values leaked
    cfg = client.get(f"/api/v1/tenants/{tid}/manage/integration", headers=admin)
    assert cfg.status_code == 200, cfg.text
    j = cfg.json()
    assert tid in j["webhook_url"] and "gophish/webhook" in j["webhook_url"]
    assert tid in j["beacon_url"] and "beacon/events" in j["beacon_url"]
    assert j["webhook_secret_set"] is False and j["ingest_token_set"] is False
    assert j["webhook_secret"] is None and j["ingest_token"] is None

    # rotate webhook secret: value shown once, status flips to set
    r = client.post(f"/api/v1/tenants/{tid}/manage/integration/rotate",
                    json={"field": "webhook_secret"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["field"] == "webhook_secret" and len(r.json()["value"]) >= 20
    assert client.get(f"/api/v1/tenants/{tid}/manage/integration",
                      headers=admin).json()["webhook_secret_set"] is True

    # operator can READ config but NOT rotate (admin-only)
    assert client.get(f"/api/v1/tenants/{tid}/manage/integration",
                      headers=op).status_code == 200
    assert client.post(f"/api/v1/tenants/{tid}/manage/integration/rotate",
                       json={"field": "ingest_token"}, headers=op).status_code == 403

    # invalid field rejected
    assert client.post(f"/api/v1/tenants/{tid}/manage/integration/rotate",
                       json={"field": "nope"}, headers=admin).status_code == 422


# ---- scoring settings (Manage -> Settings) ----
def test_scoring_settings_override_and_revert(client):
    body = _seed(client, seed=41)
    tid = body["tenant_id"]
    admin = _A(_tok(client, body, "org_admin"))
    op = _A(_tok(client, body, "operator"))

    # default: inherits server config, source reported as "default"
    r = client.get(f"/api/v1/tenants/{tid}/manage/settings", headers=admin)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["aggregation_source"] == "default"
    assert j["aggregation"] == j["default_aggregation"]
    assert set(j["options"]) == {"average", "peak", "blend"}

    # admin overrides to peak
    r = client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                     json={"aggregation": "peak"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["aggregation"] == "peak"
    assert r.json()["aggregation_source"] == "tenant"

    # override actually drives scoring: recompute, capture mean HRS under peak
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=admin)
    peak_mean = client.get(f"/api/v1/tenants/{tid}/dashboard/summary", headers=admin).json()["mean_hrs"]

    # switch to average, recompute - peak is always >= average, and with
    # multi-campaign employees the org mean must be strictly lower here.
    r = client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                     json={"aggregation": "average"}, headers=admin)
    assert r.status_code == 200
    client.post(f"/api/v1/tenants/{tid}/recompute", headers=admin)
    avg_mean = client.get(f"/api/v1/tenants/{tid}/dashboard/summary", headers=admin).json()["mean_hrs"]
    assert avg_mean < peak_mean  # the setting demonstrably changed the numbers

    # revert to server default by sending null
    r = client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                     json={"aggregation": None, "blend_alpha": None}, headers=admin)
    assert r.status_code == 200
    assert r.json()["aggregation_source"] == "default"

    # RBAC: operator can read, cannot write; invalid value rejected
    assert client.get(f"/api/v1/tenants/{tid}/manage/settings", headers=op).status_code == 200
    assert client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                        json={"aggregation": "peak"}, headers=op).status_code == 403
    assert client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                        json={"aggregation": "nope"}, headers=admin).status_code == 422
    assert client.patch(f"/api/v1/tenants/{tid}/manage/settings",
                        json={"blend_alpha": 2.0}, headers=admin).status_code == 422


# ---- integration health/status ----
def test_integration_status_reports_sources(client):
    body = _seed(client, seed=52)
    tid = body["tenant_id"]
    admin = _A(_tok(client, body, "org_admin"))

    r = client.get(f"/api/v1/tenants/{tid}/manage/integration/status", headers=admin)
    assert r.status_code == 200, r.text
    j = r.json()
    # both integration sources are always surfaced, even at zero traffic
    srcs = {s["source"]: s for s in j["sources"]}
    assert "gophish" in srcs and "beacon" in srcs
    assert srcs["gophish"]["total_events"] == 0
    assert "total_campaigns" in j and "linked_campaigns" in j
    assert j["linked_campaigns"] <= j["total_campaigns"]
