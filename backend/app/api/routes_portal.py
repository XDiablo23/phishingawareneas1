"""
Portal-facing API - the read/write surface the separate Awareness &
Remediation Portal uses to sync with PhishAwareness over REST.

The remediation portal is an independent service (its own database, its own
employee logins). It authenticates here with a per-tenant SERVICE TOKEN
(header X-Portal-Token, see require_portal_token below) scoped to exactly
this router's 5 endpoints - not the full operator/admin JWT the human
console uses. Previously the portal held a real operator/admin login and
authenticated the same way a human does, which meant a leaked portal
credential carried the full operator blast radius (campaign launch, roster,
user management), not just this narrow signal surface. It then:
  * pulls each employee's current HRS / band (to decide remediation),
  * pushes a baseline risk FLOOR after onboarding (new hire -> Moderate),
  * raises / clears the "needs in-person awareness" mark when a user is
    stuck High/Critical for too long (which the org's ticketing system
    then picks up).

Everything here is metadata and scoring signals only - no lure content and
no credentials ever cross this boundary. Tenant scoping is structural: the
token IS that tenant's own token, resolved from the tenant_id in the path,
so there is no separate enforce_tenant() check to make (unlike the
human-facing JWT routes, where one token can legitimately name a different
tenant_id than the one in the URL and must be checked).
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db import models as m
from app.scoring.service import score_tenant_from_db
from app.scoring.persist import persist_scores

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/portal", tags=["portal"])

_SENIORITY = ("Staff", "Manager", "Director", "Exec")

# Audit-log actor for every write this router makes: a fixed, recognisable
# machine identity, matching the "gophish-webhook" / "landing-beacon"
# convention already used by the other machine-to-machine endpoints.
_SERVICE_ACTOR = "portal-service"


def require_portal_token(
    tenant_id: str, db: Session = Depends(get_db),
    x_portal_token: str | None = Header(default=None),
) -> m.Tenant:
    """Authenticate the portal's automation calls via this tenant's own
    service token instead of a human operator/admin JWT. Returns the
    resolved Tenant so handlers don't need a second lookup."""
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    token = tenant.portal_service_token
    if not token or not x_portal_token or not hmac.compare_digest(token, x_portal_token):
        raise HTTPException(401, "invalid or missing portal service token")
    return tenant


def _audit(db, tenant_id, action, detail=None):
    db.add(m.AuditLog(tenant_id=tenant_id, actor=_SERVICE_ACTOR, action=action, detail=detail))


def _sl(e):
    v = getattr(e, "seniority_level", None)
    return v.value if hasattr(v, "value") else v


def _signal(db, tenant_id: str, e) -> dict:
    """The single employee 'signal' object the portal reads back: current
    score plus the two portal-written marks. HRS/band come from the cached
    score row (0 / Low before the first campaign is scored)."""
    row = (db.query(m.EmployeeScoreRow)
           .filter_by(tenant_id=tenant_id, employee_id=e.id).first())
    return {
        "employee_id": e.id,
        "email": e.email,
        "full_name": e.full_name,
        "department": e.department,
        "job_title": e.job_title,
        "seniority_level": _sl(e),
        "hrs": row.hrs if row else 0.0,
        "hrs_band": row.hrs_band if row else "Low",
        "susceptibility_index": row.susceptibility_index if row else 0.0,
        "org_risk": row.org_risk if row else 0.0,
        "campaigns_scored": row.campaigns_scored if row else 0,
        "risk_floor": e.risk_floor,
        "needs_inperson_awareness": bool(e.needs_inperson_awareness),
        "inperson_reason": e.inperson_reason,
        "inperson_since": e.inperson_since.isoformat() if e.inperson_since else None,
    }


# --- request bodies ------------------------------------------------------
class RiskFloorIn(BaseModel):
    # null clears the floor; otherwise 0..100 (portal sends ~35 for Moderate)
    value: float | None = Field(default=None, ge=0, le=100)


class InPersonFlagIn(BaseModel):
    on: bool
    reason: str | None = Field(default=None, max_length=300)


class EnsureEmployeeIn(BaseModel):
    email: str
    full_name: str
    department: str = "Unassigned"
    job_title: str = "Employee"
    seniority_level: str | None = None


# --- read: current signals ----------------------------------------------
@router.get("/employees")
def portal_list_employees(tenant_id: str, db: Session = Depends(get_db),
                          tenant: m.Tenant = Depends(require_portal_token)):
    """Every employee's current score + portal marks. The portal's periodic
    pull to decide who needs remediation."""
    emps = db.query(m.Employee).filter_by(tenant_id=tenant_id).all()
    return [_signal(db, tenant_id, e) for e in emps]


@router.get("/employees/by-email")
def portal_employee_by_email(tenant_id: str, email: str = Query(...),
                             db: Session = Depends(get_db),
                             tenant: m.Tenant = Depends(require_portal_token)):
    """One employee's signal, looked up by email (the portal's join key)."""
    e = (db.query(m.Employee)
         .filter_by(tenant_id=tenant_id, email=email).first())
    if not e:
        raise HTTPException(404, "employee not found")
    return _signal(db, tenant_id, e)


# --- write: ensure a record exists --------------------------------------
@router.post("/employees/ensure")
def portal_ensure_employee(tenant_id: str, body: EnsureEmployeeIn,
                           db: Session = Depends(get_db),
                           tenant: m.Tenant = Depends(require_portal_token)):
    """Find-or-create an employee by email so the portal can push a baseline
    on first sign-up even if HR hasn't loaded the roster yet. Idempotent:
    returns the existing record (created=false) when the email is known."""
    e = (db.query(m.Employee)
         .filter_by(tenant_id=tenant_id, email=body.email).first())
    created = False
    if not e:
        sl = body.seniority_level if body.seniority_level in _SENIORITY else None
        e = m.Employee(
            tenant_id=tenant_id, email=body.email,
            full_name=body.full_name or body.email,
            department=body.department or "Unassigned",
            job_title=body.job_title or "Employee",
            seniority_level=sl,
        )
        db.add(e)
        _audit(db, tenant_id, "portal_ensure_employee",
               {"email": body.email, "created": True})
        db.commit()
        db.refresh(e)
        created = True
    out = _signal(db, tenant_id, e)
    out["created"] = created
    return out


# --- write: baseline risk floor -----------------------------------------
@router.post("/employees/{employee_id}/risk-floor")
def portal_set_risk_floor(tenant_id: str, employee_id: str, body: RiskFloorIn,
                          db: Session = Depends(get_db),
                          tenant: m.Tenant = Depends(require_portal_token)):
    """Set (or clear, value=null) an employee's baseline HRS floor. The floor
    only ever RAISES a score and is superseded once real behaviour scores
    higher. Re-folds the tenant's cached scores so the console shows it now."""
    e = (db.query(m.Employee)
         .filter_by(tenant_id=tenant_id, id=employee_id).first())
    if not e:
        raise HTTPException(404, "employee not found")
    e.risk_floor = body.value
    _audit(db, tenant_id, "portal_set_risk_floor",
           {"employee_id": employee_id, "value": body.value})
    db.commit()
    # re-fold the floor into the cached scores (score_tenant_from_db applies it)
    emp_scores, camp_scores = score_tenant_from_db(db, tenant_id)
    persist_scores(db, tenant_id, emp_scores, camp_scores)
    db.refresh(e)
    return _signal(db, tenant_id, e)


# --- write: in-person awareness mark ------------------------------------
@router.post("/employees/{employee_id}/inperson-flag")
def portal_set_inperson_flag(tenant_id: str, employee_id: str,
                             body: InPersonFlagIn,
                             db: Session = Depends(get_db),
                             tenant: m.Tenant = Depends(require_portal_token)):
    """Raise or clear the 'needs in-person security awareness' mark. Set when
    a user is stuck High/Critical past the org's tolerance; the portal also
    raises an external ticket. `inperson_since` is stamped on first raise and
    preserved until cleared, so 'how long flagged' is measurable."""
    e = (db.query(m.Employee)
         .filter_by(tenant_id=tenant_id, id=employee_id).first())
    if not e:
        raise HTTPException(404, "employee not found")
    if body.on:
        e.needs_inperson_awareness = True
        e.inperson_reason = body.reason
        if e.inperson_since is None:
            e.inperson_since = datetime.now(timezone.utc)
    else:
        e.needs_inperson_awareness = False
        e.inperson_reason = None
        e.inperson_since = None
    _audit(db, tenant_id, "portal_set_inperson_flag",
           {"employee_id": employee_id, "on": body.on, "reason": body.reason})
    db.commit()
    db.refresh(e)
    return _signal(db, tenant_id, e)
