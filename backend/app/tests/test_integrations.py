"""
GoPhish webhook adapter tests.

Verifies signature validation, event mapping, the campaign-link flow, and
- most importantly - that a "Submitted Data" event with a captured
credential payload results in a `submitted` event with NO credential stored
anywhere.
"""

import hashlib
import hmac
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
from app.db import models as m  # noqa: E402
from app.integrations.gophish_webhook import verify_signature  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def _seed(client):
    r = client.post("/api/v1/seed/synthetic", json={"n_employees": 20, "n_campaigns": 3, "seed": 4})
    return r.json()


def _op_token(client, body):
    u = next(u for u in body["demo_users"] if u["role"] == "operator")
    r = client.post("/api/v1/auth/login",
                    data={"username": u["email"], "password": u["password"]})
    return r.json()["access_token"]


def _first_campaign_and_employee(tenant_id):
    s = base.SessionLocal()
    try:
        camp = s.query(m.Campaign).filter_by(tenant_id=tenant_id).first()
        emp = s.query(m.Employee).filter_by(tenant_id=tenant_id).first()
        return camp.id, emp.id, emp.email
    finally:
        s.close()


def test_verify_signature():
    secret = "s3cret"
    body = b'{"message":"Clicked Link"}'
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(secret, body, good)
    assert not verify_signature(secret, body, "sha256=deadbeef")
    assert not verify_signature(secret, body, None)
    assert not verify_signature(secret, body, "md5=abc")


def test_link_and_ingest_click(client):
    body = _seed(client)
    tid = body["tenant_id"]
    tok = _op_token(client, body)
    cid, eid, email = _first_campaign_and_employee(tid)

    # link this campaign to GoPhish campaign_id 42
    r = client.post(f"/api/v1/tenants/{tid}/campaigns/{cid}/link",
                    json={"external_ref": "42"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200

    payload = {"campaign_id": 42, "email": email,
               "time": "2027-01-10T12:00:00Z", "message": "Clicked Link",
               "details": json.dumps({"payload": {"rid": ["abc123"]},
                                      "browser": {"address": "1.2.3.4"}})}
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    assert r.json()["event_type"] == "clicked"


def test_submitted_data_drops_credentials(client):
    body = _seed(client)
    tid = body["tenant_id"]
    tok = _op_token(client, body)
    cid, eid, email = _first_campaign_and_employee(tid)
    client.post(f"/api/v1/tenants/{tid}/campaigns/{cid}/link",
                json={"external_ref": "77"},
                headers={"Authorization": f"Bearer {tok}"})

    # GoPhish "Submitted Data" carries the typed credentials in details.payload
    payload = {"campaign_id": 77, "email": email,
               "time": "2027-01-11T09:00:00Z", "message": "Submitted Data",
               "details": json.dumps({"payload": {
                   "rid": ["xyz"],
                   "username": ["victim@corp.example"],
                   "password": ["hunter2-SECRET"]},
                   "browser": {"address": "9.9.9.9"}})}
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}", json=payload)
    assert r.status_code == 200 and r.json()["event_type"] == "submitted"

    # The event exists, but NO credential value is stored anywhere.
    s = base.SessionLocal()
    try:
        evs = s.query(m.InteractionEvent).filter_by(
            tenant_id=tid, event_type="submitted").all()
        assert evs, "submitted event should be recorded"
        blob = json.dumps([e.event_metadata for e in evs])
        assert "hunter2-SECRET" not in blob
        assert "password" not in blob.lower()
        # only provenance + rid retained
        assert any((e.event_metadata or {}).get("source") == "gophish" for e in evs)
    finally:
        s.close()


def test_unmapped_and_ignored_events(client):
    body = _seed(client)
    tid = body["tenant_id"]

    # unknown campaign link -> unmapped (accepted, not stored). The response
    # must not echo the looked-up email/campaign back (roster-enumeration
    # guard) - only generic reason codes.
    p = {"campaign_id": 9999, "email": "nobody@northwind.example",
         "message": "Clicked Link", "details": ""}
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}", json=p)
    body2 = r.json()
    assert r.status_code == 200 and body2["status"] == "unmapped"
    assert set(body2["reasons"]) <= {"campaign_not_linked", "employee_not_found"}
    assert "nobody@northwind.example" not in json.dumps(body2)
    assert "9999" not in json.dumps(body2)

    # a non-scoring event (Email Sent) -> ignored
    p2 = {"campaign_id": 1, "email": "x@y.z", "message": "Email Sent", "details": ""}
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}", json=p2)
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def _audit_count(tenant_id):
    s = base.SessionLocal()
    try:
        return s.query(m.AuditLog).filter_by(tenant_id=tenant_id).count()
    finally:
        s.close()


def test_unmapped_webhook_is_diagnosable_server_side(client):
    """The public response stays generic (no roster oracle), but the operator
    must still be able to find out WHICH campaign/recipient failed - so the
    raw identifiers land in the tenant's own audit trail."""
    body = _seed(client)
    tid = body["tenant_id"]

    p = {"campaign_id": 4242, "email": "ghost@northwind.example",
         "message": "Clicked Link", "details": ""}
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}", json=p)
    assert r.status_code == 200 and r.json()["status"] == "unmapped"
    # still no leak in the public body
    assert "ghost@northwind.example" not in json.dumps(r.json())

    s = base.SessionLocal()
    try:
        row = (s.query(m.AuditLog)
               .filter_by(tenant_id=tid, action="ingest_gophish_event_unmapped")
               .order_by(m.AuditLog.created_at.desc()).first())
        assert row is not None, "unmapped webhook event was not audited"
        assert row.detail["email"] == "ghost@northwind.example"
        assert row.detail["campaign_ref"] == "4242"
        assert "employee_not_found" in row.detail["reasons"]
    finally:
        s.close()


def test_unmapped_beacon_is_not_audited(client):
    """Deliberate asymmetry: the beacon token is embedded in a public landing
    page, so an audit row here would let anyone who reads that page append
    unbounded rows to the tenant's audit trail. Server log only."""
    body = _seed(client)
    tid = body["tenant_id"]

    before = _audit_count(tid)
    r = client.post(
        f"/api/v1/integrations/beacon/events?tenant_id={tid}",
        json={"campaign_ref": "4242", "email": "ghost@northwind.example",
              "events": [{"type": "clicked"}]})
    assert r.status_code == 200 and r.json()["status"] == "unmapped"
    assert "ghost@northwind.example" not in json.dumps(r.json())
    assert _audit_count(tid) == before, "beacon unmapped path must not write audit rows"


def _set_tenant_webhook_secret(tenant_id, secret):
    s = base.SessionLocal()
    try:
        t = s.query(m.Tenant).filter_by(id=tenant_id).first()
        t.webhook_secret = secret
        s.commit()
    finally:
        s.close()


def test_per_tenant_webhook_secret_enforced(client):
    """A tenant's own rotated webhook secret (Manage -> Integration) is what the
    webhook verifies against - not just the server-wide env secret."""
    body = _seed(client)
    tid = body["tenant_id"]
    tok = _op_token(client, body)
    cid, eid, email = _first_campaign_and_employee(tid)
    client.post(f"/api/v1/tenants/{tid}/campaigns/{cid}/link",
                json={"external_ref": "555"},
                headers={"Authorization": f"Bearer {tok}"})

    secret = "per-tenant-secret-abc123"
    _set_tenant_webhook_secret(tid, secret)

    payload = {"campaign_id": 555, "email": email,
               "time": "2027-02-01T10:00:00Z", "message": "Clicked Link",
               "details": json.dumps({"payload": {"rid": ["r1"]}})}
    raw = json.dumps(payload).encode()

    # signed with the tenant's own secret -> accepted
    good = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}",
                    data=raw, headers={"X-Gophish-Signature": good,
                                       "Content-Type": "application/json"})
    assert r.status_code == 200 and r.json()["status"] == "recorded"

    # signed with the wrong secret -> rejected (tenant secret now governs)
    bad = "sha256=" + hmac.new(b"not-the-secret", raw, hashlib.sha256).hexdigest()
    r = client.post(f"/api/v1/integrations/gophish/webhook?tenant_id={tid}",
                    data=raw, headers={"X-Gophish-Signature": bad,
                                       "Content-Type": "application/json"})
    assert r.status_code == 401


def test_gophish_sync_reconciles_and_drops_credentials(client, monkeypatch):
    """The read-only GoPhish sync links the campaign, ingests timeline events,
    and never stores a submitted credential."""
    body = _seed(client)
    tid = body["tenant_id"]
    tok = _op_token(client, body)
    s = base.SessionLocal()
    try:
        email = s.query(m.Employee).filter_by(tenant_id=tid).first().email
    finally:
        s.close()

    sample = [{
        "id": 501, "name": "Sync Test Campaign", "status": "Completed",
        "results": [{"email": email, "first_name": "X", "last_name": "Y", "position": "Analyst"}],
        "timeline": [
            {"email": email, "message": "Email Sent", "time": "2027-03-01T09:59:00Z"},
            {"email": email, "message": "Email Opened", "time": "2027-03-01T10:00:00Z"},
            {"email": email, "message": "Clicked Link", "time": "2027-03-01T10:05:00Z"},
            {"email": email, "message": "Submitted Data", "time": "2027-03-01T10:06:00Z",
             "details": json.dumps({"payload": {"username": ["v@corp"], "password": ["SEKRET-PW"]}})},
        ],
    }]
    monkeypatch.setattr("app.integrations.gophish_sync.list_campaigns", lambda tenant: sample)

    r = client.post(f"/api/v1/tenants/{tid}/manage/integration/gophish/sync",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    out = r.json()
    assert out["campaigns_synced"] == 1
    assert out["events_ingested"] == 3   # opened, clicked, submitted (Email Sent is ignored)

    s = base.SessionLocal()
    try:
        camp = s.query(m.Campaign).filter_by(tenant_id=tid, external_ref="501").first()
        assert camp is not None, "campaign should be auto-linked by GoPhish id"
        evs = s.query(m.InteractionEvent).filter_by(tenant_id=tid, campaign_id=camp.id).all()
        assert len(evs) == 3
        blob = json.dumps([e.event_metadata for e in evs])
        assert "SEKRET-PW" not in blob
        assert "password" not in blob.lower()
        assert all((e.event_metadata or {}).get("source") == "gophish" for e in evs)
    finally:
        s.close()

    # idempotent: a second sync ingests nothing new
    r2 = client.post(f"/api/v1/tenants/{tid}/manage/integration/gophish/sync",
                     headers={"Authorization": f"Bearer {tok}"})
    assert r2.json()["events_ingested"] == 0
    assert r2.json()["skipped_existing"] == 3
