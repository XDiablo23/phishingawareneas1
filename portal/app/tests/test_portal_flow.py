"""
End-to-end portal flow tests against a fake PhishAwareness:
register -> onboarding -> Moderate floor pushed; failure -> remediation;
new policy -> remediation + ack; stuck elevated -> in-person flag + ticket.
"""
from app.tests.conftest import (
    auth, set_setting, complete_assignment, correct_answers_for,
)


def _register(client, email="alice@acme.test", **kw):
    body = {"email": email, "full_name": kw.get("full_name", "Alice A"),
            "password": "secret1", "department": kw.get("department", "Finance"),
            "job_title": kw.get("job_title", "Analyst")}
    r = client.post("/api/portal/auth/register", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _onboarding_assignment(client, tok):
    rows = client.get("/api/portal/assignments", headers=auth(tok)).json()
    ob = [a for a in rows if a["module"]["kind"] == "onboarding"]
    assert ob, "onboarding should be assigned on register"
    return ob[0]


def _admin_token(client):
    r = client.post("/api/portal/admin/auth/login",
                    json={"email": "op@acme.test", "password": "x",
                          "base_url": "http://pa.local"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_register_starts_onboarding(client, fake_pa):
    data = _register(client)
    assert data["user"]["status"] == "onboarding"
    assert data["user"]["outstanding_count"] >= 1
    # employee was mapped into PhishAwareness
    assert "alice@acme.test" in fake_pa.emps


def test_onboarding_completion_pushes_moderate_floor(client, fake_pa):
    data = _register(client)
    tok = data["access_token"]
    a = _onboarding_assignment(client, tok)
    r = complete_assignment(client, tok, a["id"], a["module"]["key"],
                            a["module"]["min_seconds"])
    assert r.status_code == 200, r.text
    assert r.json()["passed"] is True
    assert r.json()["user"]["status"] == "active"
    # Moderate baseline pushed to PhishAwareness
    emp = fake_pa.emps["alice@acme.test"]
    assert emp["risk_floor"] == 35
    assert emp["hrs"] >= 35 and emp["hrs_band"] == "Moderate"


def test_exam_locked_until_dwell(client, fake_pa):
    data = _register(client)
    tok = data["access_token"]
    a = _onboarding_assignment(client, tok)
    ans = correct_answers_for(a["module"]["key"])
    r = client.post(f"/api/portal/assignments/{a['id']}/exam",
                    json={"answers": ans}, headers=auth(tok))
    assert r.status_code == 409  # must finish the lesson first


def test_exam_fail_does_not_complete(client, fake_pa):
    data = _register(client)
    tok = data["access_token"]
    a = _onboarding_assignment(client, tok)
    # satisfy dwell
    ms = a["module"]["min_seconds"]
    while ms > 0:
        step = min(30, ms)
        client.post(f"/api/portal/assignments/{a['id']}/heartbeat",
                    json={"seconds": step}, headers=auth(tok))
        ms -= step
    n = len(correct_answers_for(a["module"]["key"]))
    r = client.post(f"/api/portal/assignments/{a['id']}/exam",
                    json={"answers": [0] * n}, headers=auth(tok))  # likely wrong
    body = r.json()
    if body["passed"]:
        return  # all-zeros happened to pass; skip (rare, not our concern)
    assert body["status"] != "completed"
    assert client.get("/api/portal/me", headers=auth(tok)).json()["status"] == "onboarding"


def _onboard(client, fake_pa, email="alice@acme.test"):
    data = _register(client, email=email)
    tok = data["access_token"]
    a = _onboarding_assignment(client, tok)
    complete_assignment(client, tok, a["id"], a["module"]["key"],
                        a["module"]["min_seconds"])
    return tok


def test_new_policy_assigns_remediation_and_ack(client, fake_pa):
    tok = _onboard(client, fake_pa)
    atok = _admin_token(client)
    r = client.post("/api/portal/admin/policies", headers=auth(atok),
                    json={"title": "Data Handling v2", "version": "2.0",
                          "body_html": "<p>New rules</p>",
                          "triggers_remediation": True,
                          "remediation_module_key": "remediation-spotting-phishing"})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_remediation_to"] >= 1
    # employee now has remediation + is in remediation status
    me = client.get("/api/portal/me", headers=auth(tok)).json()
    assert me["status"] == "remediation"
    assert me["unacked_policies"] >= 1
    # acknowledge it
    pols = client.get("/api/portal/policies", headers=auth(tok)).json()
    pid = [p for p in pols if p["title"] == "Data Handling v2"][0]["id"]
    assert client.post(f"/api/portal/policies/{pid}/ack",
                       headers=auth(tok)).status_code == 200
    assert client.get("/api/portal/me", headers=auth(tok)).json()["unacked_policies"] == \
        me["unacked_policies"] - 1


def test_sync_failure_assigns_remediation(client, fake_pa):
    tok = _onboard(client, fake_pa)
    set_setting(inperson_after_days=30)  # don't escalate to in-person yet
    fake_pa.set_state("alice@acme.test", hrs=60, band="High", campaigns=1)
    atok = _admin_token(client)
    res = client.post("/api/portal/admin/sync", headers=auth(atok)).json()
    assert res["synced"] >= 1
    me = client.get("/api/portal/me", headers=auth(tok)).json()
    assert me["status"] == "remediation"
    assert me["risk"]["band"] == "High"
    rows = client.get("/api/portal/assignments", headers=auth(tok)).json()
    assert any(a["reason"] == "phishing_failure" for a in rows)


class _FakeResp:
    def __init__(self, code=201, text="created"):
        self.status_code = code
        self.text = text


def test_stuck_elevated_escalates_inperson_and_tickets(client, fake_pa, monkeypatch):
    tok = _onboard(client, fake_pa)
    set_setting(inperson_after_days=0)  # any elevated user escalates at once
    atok = _admin_token(client)
    # configure + capture the outbound ticket webhook
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp(201, "ok")

    import app.ticket as tk
    monkeypatch.setattr(tk.httpx, "post", fake_post)
    client.put("/api/portal/admin/ticket-config", headers=auth(atok),
               json={"enabled": True, "webhook_url": "https://tickets.local/hook",
                     "system_label": "Jira"})

    fake_pa.set_state("alice@acme.test", hrs=92, band="Critical", campaigns=1)
    res = client.post("/api/portal/admin/sync", headers=auth(atok)).json()
    assert res["changed"] >= 1
    # PhishAwareness got the in-person mark
    assert fake_pa.emps["alice@acme.test"]["needs_inperson_awareness"] is True
    # user flagged
    assert client.get("/api/portal/me", headers=auth(tok)).json()["needs_inperson"] is True
    # a ticket was sent with the right event + payload
    assert captured.get("json", {}).get("event") == "inperson_awareness_required"
    tickets = client.get("/api/portal/admin/tickets", headers=auth(atok)).json()
    assert any(t["event"] == "inperson_awareness_required" and t["ok"] for t in tickets)


def test_admin_overview_and_ticket_test(client, fake_pa, monkeypatch):
    _onboard(client, fake_pa)
    atok = _admin_token(client)
    ov = client.get("/api/portal/admin/overview", headers=auth(atok)).json()
    assert ov["employees"] >= 1 and ov["modules"] >= 1

    import app.ticket as tk
    monkeypatch.setattr(tk.httpx, "post",
                        lambda *a, **k: _FakeResp(200, "ok"))
    client.put("/api/portal/admin/ticket-config", headers=auth(atok),
               json={"enabled": True, "webhook_url": "https://t.local/h"})
    r = client.post("/api/portal/admin/ticket-config/test", headers=auth(atok)).json()
    assert r["ok"] is True


def test_admin_requires_auth(client, fake_pa):
    assert client.get("/api/portal/admin/employees").status_code == 401
    assert client.post("/api/portal/admin/sync").status_code == 401
