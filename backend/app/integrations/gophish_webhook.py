"""
GoPhish webhook adapter.

GoPhish (the authorised-simulation engine) sends a webhook for each
recipient event. This endpoint receives those events and translates their
*metadata* into this platform's interaction events, so real campaigns feed
the same scoring pipeline as the synthetic demo.

SAFETY: GoPhish's "Submitted Data" event includes a `details.payload`
object containing the actual form fields the target typed - i.e. captured
credentials. This adapter parses the event only far enough to know *which
stage* was reached and **discards that payload entirely**. It records only
that a submission occurred; no submitted value is ever read into a variable
that is stored. (Best practice: also disable "Capture Passwords" in GoPhish
itself - see docs/GoPhish_Integration.md.)

GoPhish webhook payload (confirmed against the GoPhish user guide):
    { "campaign_id": 3, "email": "...", "time": "...",
      "message": "Clicked Link", "details": "<json string>" }
Signed with header  X-Gophish-Signature: sha256=<hmac-sha256 hex of body>.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import get_db
from app.db import models as m
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/integrations/gophish", tags=["integrations"])

# GoPhish event string -> our EventType value. Events with no scoring
# meaning (send/error/proxy) map to None and are acknowledged but ignored.
EVENT_MAP = {
    "Email Opened": "opened",
    "Clicked Link": "clicked",
    "Submitted Data": "submitted",
    "Email Reported": "reported",
    "Email Sent": None,
    "Error Sending Email": None,
    "Proxied request": None,
}


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Validate the X-Gophish-Signature header (sha256=<hex>) over the raw body."""
    if not header:
        return False
    prefix, _, sig = header.partition("=")
    if prefix != "sha256" or not sig:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _safe_rid(details_raw) -> str | None:
    """Extract ONLY the recipient id from `details`, discarding everything
    else (browser info and, crucially, any submitted form payload)."""
    if not details_raw:
        return None
    try:
        details = details_raw if isinstance(details_raw, dict) else json.loads(details_raw)
        payload = details.get("payload") or {}
        rid = payload.get("rid")
        if isinstance(rid, list):
            return rid[0] if rid else None
        return rid
    except (ValueError, AttributeError, TypeError):
        return None


@router.post("/webhook")
async def gophish_webhook(
    request: Request,
    tenant_id: str = Query(..., description="target tenant for these events"),
    x_gophish_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    body = await request.body()

    # 1) authenticate the sender. Prefer the per-tenant webhook secret set from
    #    Manage -> Integration; fall back to the server-wide env secret; if
    #    neither is set, accept unsigned (development only).
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    secret = tenant.webhook_secret or settings.GOPHISH_WEBHOOK_SECRET
    if secret:
        if not verify_signature(secret, body, x_gophish_signature):
            raise HTTPException(401, "invalid GoPhish webhook signature")
    elif settings.is_production():
        # Fail closed in production: never accept unsigned webhooks there.
        raise HTTPException(401, "webhook signing secret is not configured")

    # 2) parse
    try:
        evt = json.loads(body)
    except ValueError:
        raise HTTPException(400, "invalid JSON body")

    message = evt.get("message")
    if message not in EVENT_MAP:
        # unknown event type: acknowledge so GoPhish doesn't retry-storm
        return {"status": "ignored", "reason": f"unmapped message '{message}'"}
    event_type = EVENT_MAP[message]
    if event_type is None:
        return {"status": "ignored", "reason": f"'{message}' carries no scoring signal"}

    # 3) resolve campaign (by external_ref) and employee (by email)
    gp_campaign = str(evt.get("campaign_id"))
    email = (evt.get("email") or "").strip()

    campaign = db.query(m.Campaign).filter_by(
        tenant_id=tenant_id, external_ref=gp_campaign).first()
    employee = db.query(m.Employee).filter_by(
        tenant_id=tenant_id, email=email).first()

    if campaign is None or employee is None:
        # Accept (200/202-style) so GoPhish doesn't retry-storm, but keep the
        # PUBLIC response generic: this endpoint is reachable by anyone holding
        # (or having leaked) the tenant's webhook secret, and repeating "no
        # employee with email X" would let them enumerate the roster.
        #
        # The operator still has to find out *which* campaign or recipient
        # failed, so the raw identifiers are recorded where only someone with
        # real access can read them: the server log, and the tenant's own audit
        # trail. Writing the audit row is safe on this path specifically
        # because the request is HMAC-verified against the tenant's secret -
        # the beacon's equivalent path is token-gated only and therefore logs
        # without writing a row (see integrations/beacon.py).
        reasons = []
        if campaign is None:
            reasons.append("campaign_not_linked")
        if employee is None:
            reasons.append("employee_not_found")
        log.warning(
            "gophish webhook unmapped: tenant=%s campaign_ref=%s email=%s "
            "message=%s reasons=%s",
            tenant_id, gp_campaign, email or "<none>", message, ",".join(reasons))
        db.add(m.AuditLog(
            tenant_id=tenant_id, actor="gophish-webhook",
            action="ingest_gophish_event_unmapped",
            detail={"campaign_ref": gp_campaign, "email": email,
                    "message": message, "reasons": reasons},
        ))
        db.commit()
        return {"status": "unmapped", "reasons": reasons}

    # 4) parse details ONLY for the recipient id; DROP any submitted payload
    rid = _safe_rid(evt.get("details"))

    occurred = evt.get("time")
    try:
        occurred_at = datetime.fromisoformat(occurred.replace("Z", "+00:00")) \
            if occurred else datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        occurred_at = datetime.now(timezone.utc)

    db.add(m.InteractionEvent(
        tenant_id=tenant_id, campaign_id=campaign.id, employee_id=employee.id,
        event_type=event_type, value=None,
        breached=None,  # HIBP determination is out-of-band; never from GoPhish
        occurred_at=occurred_at,
        # metadata records provenance only - NEVER the submitted form data
        event_metadata={"source": "gophish", "gophish_rid": rid,
                        "gophish_event": message},
    ))
    db.add(m.AuditLog(
        tenant_id=tenant_id, actor="gophish-webhook",
        action="ingest_gophish_event",
        detail={"event": event_type, "campaign": campaign.id,
                "employee": employee.id},
    ))
    db.commit()
    return {"status": "recorded", "event_type": event_type,
            "campaign_id": campaign.id, "employee_id": employee.id}
