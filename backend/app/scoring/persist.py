"""Persist computed scores into the cache tables (idempotent per tenant)."""

from __future__ import annotations

from app.db.models import CampaignScoreRow, EmployeeScoreRow


def persist_scores(session, tenant_id: str, employee_scores, campaign_scores):
    # clear existing cached rows for this tenant
    session.query(CampaignScoreRow).filter_by(tenant_id=tenant_id).delete()
    session.query(EmployeeScoreRow).filter_by(tenant_id=tenant_id).delete()

    for emp_id, cs in campaign_scores:
        session.add(CampaignScoreRow(
            tenant_id=tenant_id, campaign_id=str(cs.campaign_id),
            employee_id=emp_id, compromise_depth=cs.compromise_depth,
            campaign_risk_severity=cs.campaign_risk_severity,
            campaign_risk_susceptibility=cs.campaign_risk_susceptibility,
            penetration_ratio=cs.penetration_ratio,
            reported=cs.reported, breached=cs.breached, reasons=cs.reasons,
        ))

    for emp_id, es in employee_scores.items():
        session.add(EmployeeScoreRow(
            tenant_id=tenant_id, employee_id=emp_id, hrs=es.hrs,
            hrs_band=es.hrs_band, susceptibility_index=es.susceptibility_index,
            org_risk=es.org_risk, campaigns_scored=es.campaigns_scored,
            summary=es.summary,
        ))
    session.commit()
