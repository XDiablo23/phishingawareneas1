"""
Outbound ticket integration. The portal only SENDS a structured JSON envelope
to a webhook the org configures (e.g. a Jira automation inbound webhook). What
happens to the ticket afterwards is entirely the org's business - we log the
attempt and the response, and stop there.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app import models as m


def _cfg(db):
    return db.query(m.TicketConfig).filter_by(id="singleton").first()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_inperson_payload(user, days: int, reason: str) -> dict:
    """A neutral, self-describing envelope. Maps cleanly onto a Jira issue
    (summary/description) or any other ticketing schema via field mapping."""
    return {
        "event": "inperson_awareness_required",
        "source": "PhishAwareness Awareness & Remediation Portal",
        "generated_at": _now_iso(),
        "severity": "high",
        "summary": f"In-person security awareness required: {user.full_name}",
        "employee": {
            "name": user.full_name,
            "email": user.email,
            "department": user.department,
            "job_title": user.job_title,
        },
        "risk": {
            "hrs": user.last_hrs,
            "band": user.last_band,
            "elevated_since": user.elevated_since.isoformat() if user.elevated_since else None,
            "days_elevated": days,
        },
        "reason": reason,
        "recommended_action": "Schedule a mandatory in-person security "
                              "awareness session; automated remediation has "
                              "not lowered this person's risk.",
        "phishawareness_employee_id": user.pa_employee_id,
    }


def _send(db, payload: dict, event: str, user=None) -> dict:
    cfg = _cfg(db)
    log = m.TicketLog(
        user_id=getattr(user, "id", None),
        user_email=getattr(user, "email", None),
        event=event, payload=payload)

    if not cfg or not cfg.enabled or not cfg.webhook_url:
        log.ok = False
        log.response_snippet = "ticketing disabled or no webhook configured"
        db.add(log)
        db.commit()
        return {"ok": False, "reason": log.response_snippet}

    headers = {"Content-Type": "application/json"}
    if cfg.auth_header_name and cfg.auth_header_value:
        headers[cfg.auth_header_name] = cfg.auth_header_value
    try:
        r = httpx.post(cfg.webhook_url, json=payload, headers=headers, timeout=10.0)
        log.status_code = r.status_code
        log.ok = 200 <= r.status_code < 300
        log.response_snippet = (r.text or "")[:300]
    except Exception as e:
        log.ok = False
        log.response_snippet = f"error: {e}"[:300]
    db.add(log)
    db.commit()
    return {"ok": log.ok, "status_code": log.status_code,
            "response": log.response_snippet}


def raise_inperson_ticket(db, user, days: int, reason: str) -> dict:
    return _send(db, build_inperson_payload(user, days, reason),
                 "inperson_awareness_required", user)


def send_test(db) -> dict:
    payload = {
        "event": "test",
        "source": "PhishAwareness Awareness & Remediation Portal",
        "generated_at": _now_iso(),
        "summary": "Test ticket from the Remediation Portal",
        "message": "If you can see this in your ticketing system, the outbound "
                   "webhook integration is working.",
    }
    return _send(db, payload, "test", None)
