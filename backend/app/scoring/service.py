"""
Scoring service: turns stored events (synthetic or DB) into scores by
calling the pure engine. Keeps the engine free of I/O concerns.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.scoring.engine import (
    Event, CampaignContext, CampaignScore, EmployeeScore,
    score_campaign, score_employee,
)


def _agg() -> str:
    try:
        from app.config import settings
        return settings.HRS_AGGREGATION
    except Exception:
        return "average"


def _alpha() -> float:
    try:
        from app.config import settings
        return settings.HRS_BLEND_ALPHA
    except Exception:
        return 0.5


VALID_AGGREGATIONS = ("average", "peak", "blend")


def resolve_scoring_settings(tenant=None) -> tuple[str, float]:
    """Effective (aggregation, blend_alpha) for a tenant.

    A tenant may override the server default from Manage -> Settings; a NULL
    column means "inherit the env default". Invalid stored values fall back
    to the default rather than raising, so scoring can never be wedged by a
    bad setting.
    """
    agg, alpha = _agg(), _alpha()
    if tenant is not None:
        t_agg = getattr(tenant, "hrs_aggregation", None)
        t_alpha = getattr(tenant, "hrs_blend_alpha", None)
        if t_agg in VALID_AGGREGATIONS:
            agg = t_agg
        if t_alpha is not None:
            alpha = min(max(float(t_alpha), 0.0), 1.0)
    return agg, alpha


def score_synthetic(dataset, as_of: Optional[datetime] = None):
    """Score an in-memory synthetic dataset.

    Returns (employee_scores, campaign_scores) where:
      employee_scores : {employee_id: EmployeeScore}
      campaign_scores : list[(employee_id, CampaignScore)]
    """
    as_of = as_of or datetime.now(timezone.utc)

    # index events by (employee, campaign)
    grouped: dict[tuple[str, str], list[Event]] = defaultdict(list)
    for ev in dataset.events:
        grouped[(ev.employee_id, ev.campaign_id)].append(
            Event(event_type=ev.event_type, value=ev.value,
                  breached=ev.breached, occurred_at=ev.occurred_at)
        )

    camp_by_id = {c.campaign_id: c for c in dataset.campaigns}

    per_employee: dict[str, list[CampaignScore]] = defaultdict(list)
    campaign_scores: list[tuple[str, CampaignScore]] = []

    for (emp_id, cid), events in grouped.items():
        vector, eff_tier = dataset.assigned[(cid, emp_id)]
        ctx = CampaignContext(
            campaign_id=cid, tier=eff_tier, vector=vector,
            campaign_date=camp_by_id[cid].campaign_date,
        )
        cs = score_campaign(events, ctx)
        per_employee[emp_id].append(cs)
        campaign_scores.append((emp_id, cs))

    seniority = {e.employee_id: e.seniority_level for e in dataset.employees}
    employee_scores: dict[str, EmployeeScore] = {}
    for emp in dataset.employees:
        cs_list = per_employee.get(emp.employee_id, [])
        employee_scores[emp.employee_id] = score_employee(
            cs_list, seniority_level=seniority.get(emp.employee_id), as_of=as_of,
            aggregation=_agg(), blend_alpha=_alpha())

    return employee_scores, campaign_scores


def score_tenant_from_db(session, tenant_id: str,
                         as_of: Optional[datetime] = None):
    """Score a tenant's employees from persisted InteractionEvent rows.

    Uses each target's `assigned_vector` and `effective_tier` so 'mixed'
    campaigns and Tier-3 fallbacks are scored on the concrete vector/tier.
    """
    from app.db.models import (
        InteractionEvent, Campaign, CampaignTarget, Employee, Tenant,
    )
    as_of = as_of or datetime.now(timezone.utc)

    tenant = session.query(Tenant).filter_by(id=tenant_id).first()
    agg, alpha = resolve_scoring_settings(tenant)

    campaigns = {c.id: c for c in
                 session.query(Campaign).filter_by(tenant_id=tenant_id).all()}
    targets = {(t.campaign_id, t.employee_id): t for t in
               session.query(CampaignTarget).filter_by(tenant_id=tenant_id).all()}
    employees = session.query(Employee).filter_by(tenant_id=tenant_id).all()

    grouped: dict[tuple[str, str], list[Event]] = defaultdict(list)
    rows = session.query(InteractionEvent).filter_by(tenant_id=tenant_id).all()
    for r in rows:
        grouped[(r.employee_id, r.campaign_id)].append(
            Event(event_type=r.event_type.value if hasattr(r.event_type, "value")
                  else r.event_type,
                  value=r.value, breached=r.breached, occurred_at=r.occurred_at)
        )

    per_employee: dict[str, list[CampaignScore]] = defaultdict(list)
    campaign_scores: list[tuple[str, CampaignScore]] = []

    for (emp_id, cid), events in grouped.items():
        tgt = targets.get((cid, emp_id))
        camp = campaigns.get(cid)
        if camp is None:
            continue
        if tgt is not None:
            vector = tgt.assigned_vector.value if hasattr(tgt.assigned_vector, "value") else tgt.assigned_vector
            eff_tier = tgt.effective_tier
        else:
            vector = camp.attack_vector.value if hasattr(camp.attack_vector, "value") else camp.attack_vector
            eff_tier = camp.tier
        ctx = CampaignContext(campaign_id=cid, tier=eff_tier, vector=vector,
                              campaign_date=camp.created_at)
        cs = score_campaign(events, ctx)
        per_employee[emp_id].append(cs)
        campaign_scores.append((emp_id, cs))

    employee_scores: dict[str, EmployeeScore] = {}
    for emp in employees:
        sl = emp.seniority_level.value if getattr(emp, "seniority_level", None) \
            and hasattr(emp.seniority_level, "value") else emp.seniority_level
        employee_scores[emp.id] = score_employee(
            per_employee.get(emp.id, []), seniority_level=sl, as_of=as_of,
            aggregation=agg, blend_alpha=alpha)

    # Apply any per-employee baseline floor written by the remediation portal
    # (e.g. a new hire held at Moderate after onboarding). The floor only ever
    # raises a score, never lowers it, and is superseded once real behaviour
    # produces a higher HRS.
    from app.scoring.engine import _band_for
    for emp in employees:
        es = employee_scores.get(emp.id)
        floor = getattr(emp, "risk_floor", None)
        if es is not None and floor and es.hrs < float(floor):
            es.hrs = round(float(floor), 1)
            es.hrs_band = _band_for(es.hrs)
            es.org_risk = round(es.hrs * es.role_sensitivity, 1)

    return employee_scores, campaign_scores
