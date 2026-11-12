"""
Dashboard read API - the five views, role-scoped.

Access model:
  * super_admin / org_admin / operator : whole tenant
  * dept_viewer                        : restricted to their department

All aggregates are computed over the *visible* employee set so a
departmental viewer's summary, heatmap, and campaign stats only reflect
their own department.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db import models as m
from app.scoring import constants as C
from app.api.security import (
    require_roles, enforce_tenant, dept_filter_for, CurrentUser,
)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/dashboard", tags=["dashboard"])

_ANY_ROLE = require_roles("org_admin", "operator", "dept_viewer")


def _visible_employees(db: Session, tenant_id: str, user: CurrentUser):
    q = db.query(m.Employee).filter_by(tenant_id=tenant_id)
    dept = dept_filter_for(user)
    if dept:
        q = q.filter(m.Employee.department == dept)
    return q.all()


def _sl(e) -> str | None:
    return e.seniority_level.value if e.seniority_level and hasattr(
        e.seniority_level, "value") else e.seniority_level


# --- View 4: org summary -------------------------------------------------
@router.get("/summary")
def summary(tenant_id: str, db: Session = Depends(get_db),
            user: CurrentUser = Depends(_ANY_ROLE)):
    enforce_tenant(user, tenant_id)
    emps = _visible_employees(db, tenant_id, user)
    ids = {e.id for e in emps}
    scores = [r for r in db.query(m.EmployeeScoreRow).filter_by(tenant_id=tenant_id).all()
              if r.employee_id in ids]

    bands = {label: 0 for _, _, label in C.BANDS}
    hrs_vals, sus_vals = [], []
    for r in scores:
        bands[r.hrs_band] = bands.get(r.hrs_band, 0) + 1
        hrs_vals.append(r.hrs)
        sus_vals.append(r.susceptibility_index)

    breached = (db.query(m.CampaignScoreRow)
                .filter_by(tenant_id=tenant_id, breached=True).count())
    n_campaigns = db.query(m.Campaign).filter_by(tenant_id=tenant_id).count()

    return {
        "employees": len(emps),
        "scored": len(scores),
        "campaigns": n_campaigns,
        "band_distribution": bands,
        "mean_hrs": round(sum(hrs_vals) / len(hrs_vals), 1) if hrs_vals else 0,
        "max_hrs": round(max(hrs_vals), 1) if hrs_vals else 0,
        "mean_susceptibility": round(sum(sus_vals) / len(sus_vals), 1) if sus_vals else 0,
        "employees_with_breached_submission": breached,
        "scope": {"department": dept_filter_for(user)},
    }


# --- View 2: department heatmap -----------------------------------------
@router.get("/departments")
def departments(tenant_id: str, db: Session = Depends(get_db),
                user: CurrentUser = Depends(_ANY_ROLE)):
    enforce_tenant(user, tenant_id)
    emps = _visible_employees(db, tenant_id, user)
    by_id = {e.id: e for e in emps}
    scores = [r for r in db.query(m.EmployeeScoreRow).filter_by(tenant_id=tenant_id).all()
              if r.employee_id in by_id]

    agg = defaultdict(lambda: {"count": 0, "hrs_sum": 0.0, "sus_sum": 0.0,
                               "worst_hrs": 0.0})
    for r in scores:
        dept = by_id[r.employee_id].department
        a = agg[dept]
        a["count"] += 1
        a["hrs_sum"] += r.hrs
        a["sus_sum"] += r.susceptibility_index
        a["worst_hrs"] = max(a["worst_hrs"], r.hrs)

    def band_of(x):
        for lo, hi, label in C.BANDS:
            if lo <= x <= hi:
                return label
        return "Critical"

    out = []
    for dept, a in sorted(agg.items()):
        mean_hrs = a["hrs_sum"] / a["count"] if a["count"] else 0
        out.append({
            "department": dept, "employees": a["count"],
            "mean_hrs": round(mean_hrs, 1), "band": band_of(mean_hrs),
            "mean_susceptibility": round(a["sus_sum"] / a["count"], 1) if a["count"] else 0,
            "worst_hrs": round(a["worst_hrs"], 1),
        })
    return out


# --- View 3: per-campaign aggregates ------------------------------------
@router.get("/campaigns")
def campaigns(tenant_id: str, db: Session = Depends(get_db),
              user: CurrentUser = Depends(_ANY_ROLE)):
    enforce_tenant(user, tenant_id)
    visible_ids = {e.id for e in _visible_employees(db, tenant_id, user)}
    camps = db.query(m.Campaign).filter_by(tenant_id=tenant_id).all()
    events = db.query(m.InteractionEvent).filter_by(tenant_id=tenant_id).all()
    cscores = db.query(m.CampaignScoreRow).filter_by(tenant_id=tenant_id).all()

    ev_by_camp = defaultdict(lambda: defaultdict(set))  # camp -> etype -> {emp}
    for e in events:
        if e.employee_id in visible_ids:
            et = e.event_type.value if hasattr(e.event_type, "value") else e.event_type
            ev_by_camp[e.campaign_id][et].add(e.employee_id)

    depth_by_camp = defaultdict(list)
    for r in cscores:
        if r.employee_id in visible_ids:
            depth_by_camp[r.campaign_id].append(r.compromise_depth)

    out = []
    for c in camps:
        stats = ev_by_camp.get(c.id, {})
        depths = depth_by_camp.get(c.id, [])
        vec = c.attack_vector.value if hasattr(c.attack_vector, "value") else c.attack_vector
        targeted = db.query(m.CampaignTarget).filter_by(
            tenant_id=tenant_id, campaign_id=c.id).count()
        out.append({
            "campaign_id": c.id, "name": c.name, "tier": c.tier, "vector": vec,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "targets": targeted,
            "opened": len(stats.get("opened", set())),
            "clicked": len(stats.get("clicked", set())),
            "submitted": len(stats.get("submitted", set())),
            "downloaded": len(stats.get("download", set())),
            "reported": len(stats.get("reported", set())),
            "mean_depth": round(sum(depths) / len(depths), 1) if depths else 0,
        })
    out.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return out


# --- View 1: employee list ----------------------------------------------
_EMP_SORT_KEYS = {
    "hrs": lambda r: r["hrs"],
    "org_risk": lambda r: r["org_risk"],
    "susceptibility": lambda r: r["susceptibility_index"],
    "campaigns": lambda r: r["campaigns_scored"],
    "name": lambda r: (r["full_name"] or "").lower(),
    "department": lambda r: ((r["department"] or "").lower(),
                             -r["hrs"]),
}


@router.get("/employees")
def employees(tenant_id: str, department: str | None = Query(None),
              band: str | None = Query(None),
              seniority: str | None = Query(None),
              q: str | None = Query(None, description="name/title search"),
              sort: str = Query("hrs"),
              order: str = Query("desc"),
              db: Session = Depends(get_db),
              user: CurrentUser = Depends(_ANY_ROLE)):
    enforce_tenant(user, tenant_id)
    if sort not in _EMP_SORT_KEYS:
        raise HTTPException(422, f"sort must be one of {sorted(_EMP_SORT_KEYS)}")
    if order not in ("asc", "desc"):
        raise HTTPException(422, "order must be 'asc' or 'desc'")
    emps = {e.id: e for e in _visible_employees(db, tenant_id, user)}
    rows = db.query(m.EmployeeScoreRow).filter_by(tenant_id=tenant_id).all()
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        e = emps.get(r.employee_id)
        if not e:
            continue
        if department and e.department != department:
            continue
        if band and r.hrs_band != band:
            continue
        if seniority and _sl(e) != seniority:
            continue
        if needle and needle not in (e.full_name or "").lower() \
                and needle not in (e.job_title or "").lower():
            continue
        out.append({
            "employee_id": r.employee_id, "full_name": e.full_name,
            "department": e.department, "job_title": e.job_title,
            "seniority_level": _sl(e), "hrs": r.hrs, "hrs_band": r.hrs_band,
            "susceptibility_index": r.susceptibility_index,
            "org_risk": r.org_risk, "campaigns_scored": r.campaigns_scored,
            "needs_inperson_awareness": bool(getattr(e, "needs_inperson_awareness", False)),
            "risk_floor": getattr(e, "risk_floor", None),
        })
    out.sort(key=_EMP_SORT_KEYS[sort], reverse=(order == "desc"))
    return out


# --- View 5: drill-down --------------------------------------------------
@router.get("/employees/{employee_id}")
def employee_detail(tenant_id: str, employee_id: str,
                    db: Session = Depends(get_db),
                    user: CurrentUser = Depends(_ANY_ROLE)):
    enforce_tenant(user, tenant_id)
    e = db.query(m.Employee).filter_by(tenant_id=tenant_id, id=employee_id).first()
    if not e:
        raise HTTPException(404, "employee not found")
    dept = dept_filter_for(user)
    if dept and e.department != dept:
        raise HTTPException(403, "outside your department scope")

    head = db.query(m.EmployeeScoreRow).filter_by(
        tenant_id=tenant_id, employee_id=employee_id).first()
    camps = db.query(m.CampaignScoreRow).filter_by(
        tenant_id=tenant_id, employee_id=employee_id).all()
    campaigns = {c.id: c for c in db.query(m.Campaign).filter_by(tenant_id=tenant_id).all()}

    def cv(c):
        camp = campaigns.get(c.campaign_id)
        vec = camp.attack_vector.value if camp and hasattr(camp.attack_vector, "value") else (camp.attack_vector if camp else "")
        return {"campaign_id": c.campaign_id, "campaign_name": camp.name if camp else "",
                "tier": camp.tier if camp else None, "vector": vec,
                "compromise_depth": c.compromise_depth,
                "campaign_risk_severity": c.campaign_risk_severity,
                "campaign_risk_susceptibility": c.campaign_risk_susceptibility,
                "penetration_ratio": c.penetration_ratio, "reported": c.reported,
                "breached": c.breached, "reasons": c.reasons or []}

    campaign_rows = sorted([cv(c) for c in camps],
                           key=lambda x: x["campaign_risk_severity"], reverse=True)
    return {
        "employee_id": e.id, "full_name": e.full_name, "email": e.email,
        "department": e.department, "job_title": e.job_title,
        "seniority_level": _sl(e),
        "hrs": head.hrs if head else 0, "hrs_band": head.hrs_band if head else "Low",
        "susceptibility_index": head.susceptibility_index if head else 0,
        "org_risk": head.org_risk if head else 0,
        "summary": head.summary if head else "",
        "needs_inperson_awareness": bool(getattr(e, "needs_inperson_awareness", False)),
        "inperson_reason": getattr(e, "inperson_reason", None),
        "inperson_since": e.inperson_since.isoformat() if getattr(e, "inperson_since", None) else None,
        "risk_floor": getattr(e, "risk_floor", None),
        "campaigns": campaign_rows,
    }


# --- Trends: HRS over time -----------------------------------------------
# The engine is deterministic and takes an `as_of`, so a trend is just the
# same scoring evaluated at several past dates. Decay (90-day half-life) means
# older failures weigh less at each point, which is exactly the "improvement
# lowers the score" behaviour we want to show - no historical snapshot table
# required.
from datetime import datetime, timedelta, timezone   # noqa: E402
from app.scoring.service import score_tenant_from_db  # noqa: E402


def _trend_dates(weeks: int, step_days: int) -> list[datetime]:
    now = datetime.now(timezone.utc)
    n = max(2, min(weeks, 52))
    dates = [now - timedelta(days=step_days * i) for i in range(n)]
    return list(reversed(dates))          # oldest -> newest


@router.get("/trend")
def org_trend(tenant_id: str, weeks: int = Query(8, ge=2, le=52),
              step_days: int = Query(7, ge=1, le=30),
              db: Session = Depends(get_db),
              user: CurrentUser = Depends(_ANY_ROLE)):
    """Org-level HRS trend: mean HRS and High/Critical headcount per point.

    Respects the caller's visibility scope (a dept viewer sees only their
    department's trend)."""
    enforce_tenant(user, tenant_id)
    visible = {e.id for e in _visible_employees(db, tenant_id, user)}
    if not visible:
        return {"points": []}
    points = []
    for as_of in _trend_dates(weeks, step_days):
        emp_scores, _ = score_tenant_from_db(db, tenant_id, as_of=as_of)
        vals = [s.hrs for eid, s in emp_scores.items() if eid in visible]
        if not vals:
            points.append({"date": as_of.date().isoformat(), "mean_hrs": 0,
                           "high_or_critical": 0, "n": 0})
            continue
        hi = sum(1 for v in vals if v >= 50)
        points.append({
            "date": as_of.date().isoformat(),
            "mean_hrs": round(sum(vals) / len(vals), 1),
            "high_or_critical": hi, "n": len(vals),
        })
    return {"points": points}


@router.get("/employees/{employee_id}/trend")
def employee_trend(tenant_id: str, employee_id: str,
                   weeks: int = Query(8, ge=2, le=52),
                   step_days: int = Query(7, ge=1, le=30),
                   db: Session = Depends(get_db),
                   user: CurrentUser = Depends(_ANY_ROLE)):
    """Per-person HRS trend across the same date grid."""
    enforce_tenant(user, tenant_id)
    visible = {e.id for e in _visible_employees(db, tenant_id, user)}
    if employee_id not in visible:
        raise HTTPException(404, "employee not found in your scope")
    points = []
    for as_of in _trend_dates(weeks, step_days):
        emp_scores, _ = score_tenant_from_db(db, tenant_id, as_of=as_of)
        s = emp_scores.get(employee_id)
        points.append({
            "date": as_of.date().isoformat(),
            "hrs": s.hrs if s else 0,
            "hrs_band": s.hrs_band if s else "Low",
            "susceptibility_index": s.susceptibility_index if s else 0,
        })
    return {"employee_id": employee_id, "points": points}
