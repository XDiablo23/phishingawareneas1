"""
Landing-page beacon ingestion - the metadata front door.

GoPhish emits only the coarse backbone (opened / clicked / submitted /
reported). The signals that light up the compromise-depth ladder - how long
someone lingered, whether they *focused* a credential field, whether they
*typed* without submitting - have to come from the simulation landing page
itself. This endpoint accepts exactly those signals and nothing else.

PRIVACY - the whole reason this is safe to run:
  * It records that an interaction *happened*, never its content.
  * The ONLY numeric payload accepted is `dwell` seconds. Every other event
    carries no value at all. A request is rejected outright if any event
    smells like a credential (a password/secret field, or a non-dwell event
    trying to smuggle a string value).
  * Nothing here can store a keystroke or a form value, by construction - it
    never reads one. The client beacon is built the same way.

This mirrors the GoPhish webhook: public (landing pages can't carry admin
auth), tenant-scoped by query param, guarded by a shared token, resolving
campaign by external_ref and employee by email.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as m
from app.db.base import get_db
from app.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/integrations/beacon", tags=["integrations"])

# Only the rich, content-free signals the landing page can observe. Note the
# absence of `opened` (that's the tracking pixel's job) and anything chatbot/
# download - those arrive through their own adapters. `clicked` is accepted
# because loading the landing page *is* the click-through.
ALLOWED_EVENTS = {"clicked", "dwell", "field_focus", "typed_no_submit", "submitted"}

# Substrings that must never appear as an event field. If we see one, the
# sender is trying to push content we refuse to store - reject the batch.
_CREDENTIAL_MARKERS = ("password", "passwd", "pwd", "secret", "credential",
                       "otp", "token", "ssn", "card", "cvv", "value")


class BeaconEvent(BaseModel):
    model_config = {"extra": "forbid"}          # reject any unexpected field
    type: str
    seconds: float | None = Field(default=None, ge=0, le=86400)

    @field_validator("type")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in ALLOWED_EVENTS:
            raise ValueError(f"event type '{v}' not accepted by the beacon")
        return v

    @field_validator("seconds")
    @classmethod
    def _seconds_only_for_dwell(cls, v, info):
        # `seconds` is meaningful only for dwell; forbid it elsewhere so no
        # event can carry a smuggled scalar.
        if v is not None and info.data.get("type") != "dwell":
            raise ValueError("only 'dwell' may carry seconds")
        return v


class BeaconBatch(BaseModel):
    model_config = {"extra": "forbid"}
    token: str | None = None
    campaign_ref: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    events: list[BeaconEvent] = Field(..., min_length=1, max_length=50)


# The endpoint's own legitimate keys - never flag these as credential-shaped.
_ALLOWED_KEYS = {"token", "campaign_ref", "email", "events", "type", "seconds"}


def _reject_credential_shapes(raw: dict) -> None:
    """Defence in depth: any *unexpected* key resembling a credential rejects
    the batch. (The schema already forbids extra fields; this is belt-and-
    suspenders and skips our own known keys so `token` isn't self-flagged.)"""
    def walk(obj):
        if isinstance(obj, dict):
            for k, val in obj.items():
                kl = str(k).lower()
                if kl not in _ALLOWED_KEYS and any(
                        mark in kl for mark in _CREDENTIAL_MARKERS):
                    raise HTTPException(
                        422, "beacon rejects credential-like fields")
                walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(raw)


@router.post("/events")
async def ingest_beacon(
    batch: BeaconBatch,
    tenant_id: str = Query(..., description="target tenant for these events"),
    db: Session = Depends(get_db),
):
    # 1) resolve tenant, then token-gate. Prefer the per-tenant beacon token set
    #    from Manage -> Integration; fall back to the server-wide env token; if
    #    neither is set, accept unsigned (development only).
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    token = tenant.ingest_token or settings.BEACON_INGEST_TOKEN
    if token:
        if batch.token != token:
            raise HTTPException(401, "invalid beacon token")
    elif settings.is_production():
        # Fail closed in production: never accept unsigned beacon posts there.
        raise HTTPException(401, "beacon ingest token is not configured")

    # 2) defence in depth against credential-shaped payloads
    _reject_credential_shapes(batch.model_dump())

    email = batch.email.strip().lower()
    campaign = db.query(m.Campaign).filter_by(
        tenant_id=tenant_id, external_ref=batch.campaign_ref).first()
    employee = db.query(m.Employee).filter_by(
        tenant_id=tenant_id, email=email).first()

    if campaign is None or employee is None:
        # Same reasoning as the GoPhish webhook: accept (so a misconfigured
        # page doesn't error out) but don't echo the looked-up campaign_ref
        # or email back - this public, only token-gated endpoint shouldn't
        # double as a roster-enumeration oracle.
        #
        # The identifiers go to the server log ONLY - deliberately no AuditLog
        # row here, unlike the webhook. The beacon token is embedded in a
        # public landing page (a spam-guard, not a secret), so anyone who
        # views the page can post here; an audit write would let them append
        # unbounded rows to the tenant's audit trail. A rotated server log
        # absorbs that abuse, the audit table would not.
        reasons = []
        if campaign is None:
            reasons.append("campaign_not_linked")
        if employee is None:
            reasons.append("employee_not_found")
        log.warning(
            "beacon unmapped: tenant=%s campaign_ref=%s email=%s reasons=%s",
            tenant_id, batch.campaign_ref, email or "<none>", ",".join(reasons))
        return {"status": "unmapped", "reasons": reasons}

    now = datetime.now(timezone.utc)
    stored = 0
    for ev in batch.events:
        db.add(m.InteractionEvent(
            tenant_id=tenant_id, campaign_id=campaign.id,
            employee_id=employee.id,
            event_type=ev.type,
            value=ev.seconds if ev.type == "dwell" else None,
            breached=None,
            occurred_at=now,
            event_metadata={"source": "beacon"},   # provenance only
        ))
        stored += 1

    db.add(m.AuditLog(
        tenant_id=tenant_id, actor="landing-beacon",
        action="ingest_beacon_events",
        detail={"campaign": campaign.id, "employee": employee.id,
                "count": stored},
    ))
    db.commit()
    return {"status": "recorded", "stored": stored,
            "campaign_id": campaign.id, "employee_id": employee.id}
