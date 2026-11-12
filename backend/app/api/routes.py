"""API routes: ingestion + scoring.

Endpoints
---------
POST /api/v1/seed/synthetic                     seed a demo tenant (dev/test)
POST /api/v1/tenants/{tid}/events               ingest a batch of events (JSON)
POST /api/v1/tenants/{tid}/events/csv           ingest events from a CSV upload
POST /api/v1/tenants/{tid}/recompute            recompute + cache all scores
GET  /api/v1/tenants/{tid}/scores               list employee scores
GET  /api/v1/tenants/{tid}/employees/{eid}/score  one employee, with campaigns
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db import models as m
from app.api import schemas as s
from app.api.schemas import EVENT_TYPES, _FORBIDDEN_KEYS
from app.api.security import require_roles, enforce_tenant, hash_password, CurrentUser
from app.scoring.service import score_tenant_from_db
from app.scoring.persist import persist_scores
from app.synthetic import generate_dataset

router = APIRouter(prefix="/api/v1")

# Demo-only console users created alongside a synthetic tenant so the
# console is immediately usable. NOT for production. Emails are namespaced
# per tenant (email is globally unique) and returned by /seed.
DEMO_USERS = [
    ("admin", m.UserRole.org_admin, None, "admin-demo-pass"),
    ("operator", m.UserRole.operator, None, "operator-demo-pass"),
    ("viewer", m.UserRole.dept_viewer, "Finance", "viewer-demo-pass"),
]


def _audit(db: Session, tenant_id, actor, action, detail=None):
    db.add(m.AuditLog(tenant_id=tenant_id, actor=actor, action=action, detail=detail))


# --- seeding -------------------------------------------------------------
@router.post("/seed/synthetic", response_model=s.SeedResult)
def seed_synthetic(req: s.SeedRequest, db: Session = Depends(get_db)):
    """Create a full synthetic tenant (employees, campaigns, targets, events)
    plus demo console users. Generates event metadata only - nothing is
    sent, cloned, or captured. Dev/demo convenience; disabled in production."""
    from app.config import settings
    if settings.is_production():
        raise HTTPException(403, "synthetic seeding is disabled in production")
    ds = generate_dataset(n_employees=req.n_employees,
                          n_campaigns=req.n_campaigns, seed=req.seed,
                          tenant_name=req.tenant_name)

    tenant = m.Tenant(name=ds.tenant_name)
    db.add(tenant)
    db.flush()

    id_map: dict[str, str] = {}
    for e in ds.employees:
        row = m.Employee(
            tenant_id=tenant.id, full_name=e.full_name, email=e.email,
            department=e.department, job_title=e.job_title,
            manager_email=e.manager_email, seniority_level=e.seniority_level,
        )
        db.add(row)
        db.flush()
        id_map[e.employee_id] = row.id

    camp_map: dict[str, str] = {}
    for c in ds.campaigns:
        row = m.Campaign(
            tenant_id=tenant.id, name=c.name, tier=c.tier,
            attack_vector=c.vector, status=m.CampaignStatus.completed,
            created_at=c.campaign_date,
        )
        db.add(row)
        db.flush()
        camp_map[c.campaign_id] = row.id
        # targets
        for eid in c.target_ids:
            vector, eff_tier = ds.assigned[(c.campaign_id, eid)]
            db.add(m.CampaignTarget(
                tenant_id=tenant.id, campaign_id=row.id,
                employee_id=id_map[eid], assigned_vector=vector,
                effective_tier=eff_tier))

    for ev in ds.events:
        db.add(m.InteractionEvent(
            tenant_id=tenant.id, campaign_id=camp_map[ev.campaign_id],
            employee_id=id_map[ev.employee_id], event_type=ev.event_type,
            value=ev.value, breached=ev.breached, occurred_at=ev.occurred_at))

    # demo console users (one per role) so the dashboard is usable immediately
    demo = []
    suffix = tenant.id[:8]
    for localpart, role, dept, pw in DEMO_USERS:
        email = f"{localpart}+{suffix}@demo.local"
        db.add(m.User(tenant_id=tenant.id, email=email,
                      password_hash=hash_password(pw), role=role,
                      department_scope=dept))
        demo.append({"email": email,
                     "role": role.value if hasattr(role, "value") else role,
                     "password": pw, "department_scope": dept})

    _audit(db, tenant.id, "seed-synthetic", "seed_synthetic",
           {"employees": len(ds.employees), "campaigns": len(ds.campaigns)})
    db.commit()
    return s.SeedResult(tenant_id=tenant.id, tenant_name=ds.tenant_name,
                        employees=len(ds.employees),
                        campaigns=len(ds.campaigns), events=len(ds.events),
                        demo_users=demo)


# --- ingestion -----------------------------------------------------------
@router.post("/tenants/{tenant_id}/events", response_model=s.IngestResult)
def ingest_events(tenant_id: str, batch: s.EventBatchIn,
                  db: Session = Depends(get_db),
                  user: CurrentUser = Depends(require_roles("org_admin", "operator"))):
    enforce_tenant(user, tenant_id)
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")
    # Only accept references to THIS tenant's own campaigns/employees.
    valid_campaigns = {r.id for r in db.query(m.Campaign.id).filter_by(tenant_id=tenant_id)}
    valid_employees = {r.id for r in db.query(m.Employee.id).filter_by(tenant_id=tenant_id)}
    n = rejected = 0
    for ev in batch.events:
        if ev.campaign_id not in valid_campaigns or ev.employee_id not in valid_employees:
            rejected += 1
            continue
        db.add(m.InteractionEvent(
            tenant_id=tenant_id, campaign_id=ev.campaign_id,
            employee_id=ev.employee_id, event_type=ev.event_type,
            value=ev.value, breached=ev.breached,
            occurred_at=ev.occurred_at or datetime.now(timezone.utc),
            event_metadata=ev.event_metadata))
        n += 1
    _audit(db, tenant_id, user.email, "ingest_events", {"count": n, "rejected": rejected})
    db.commit()
    return s.IngestResult(ingested=n, rejected=rejected, tenant_id=tenant_id)


@router.post("/tenants/{tenant_id}/events/csv", response_model=s.IngestResult)
async def ingest_events_csv(tenant_id: str, file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user: CurrentUser = Depends(require_roles("org_admin", "operator"))):
    """CSV columns: campaign_id,employee_id,event_type,value,breached,occurred_at
    `value`, `breached`, `occurred_at` are optional. Credential-like columns
    are rejected."""
    enforce_tenant(user, tenant_id)
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")

    from app.api.uploads import read_upload_capped
    raw = (await read_upload_capped(file)).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    header_lower = {h.strip().lower() for h in (reader.fieldnames or [])}
    bad = header_lower & _FORBIDDEN_KEYS
    if bad:
        raise HTTPException(400, f"credential-like columns not accepted: {sorted(bad)}")
    required = {"campaign_id", "employee_id", "event_type"}
    if not required <= header_lower:
        raise HTTPException(400, f"CSV missing required columns: {sorted(required - header_lower)}")

    # Only accept references to THIS tenant's own campaigns/employees, so a
    # crafted CSV can't attach events to another tenant's rows.
    valid_campaigns = {r.id for r in db.query(m.Campaign.id).filter_by(tenant_id=tenant_id)}
    valid_employees = {r.id for r in db.query(m.Employee.id).filter_by(tenant_id=tenant_id)}

    ingested = rejected = 0
    for row in reader:
        try:
            et = (row.get("event_type") or "").strip()
            cid = (row.get("campaign_id") or "").strip()
            eid = (row.get("employee_id") or "").strip()
            if et not in EVENT_TYPES or cid not in valid_campaigns or eid not in valid_employees:
                rejected += 1
                continue
            val = row.get("value")
            br = (row.get("breached") or "").strip().lower()
            occ = (row.get("occurred_at") or "").strip()
            db.add(m.InteractionEvent(
                tenant_id=tenant_id, campaign_id=cid, employee_id=eid, event_type=et,
                value=float(val) if val not in (None, "") else None,
                breached=(br in ("1", "true", "yes")) if br else None,
                occurred_at=datetime.fromisoformat(occ) if occ else datetime.now(timezone.utc),
            ))
            ingested += 1
        except (ValueError, KeyError, TypeError):
            rejected += 1
    _audit(db, tenant_id, user.email, "ingest_csv", {"ingested": ingested, "rejected": rejected})
    db.commit()
    return s.IngestResult(ingested=ingested, rejected=rejected, tenant_id=tenant_id)


# --- scoring -------------------------------------------------------------
@router.post("/tenants/{tenant_id}/recompute")
def recompute(tenant_id: str, db: Session = Depends(get_db),
              user: CurrentUser = Depends(require_roles("org_admin", "operator"))):
    enforce_tenant(user, tenant_id)
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")
    emp_scores, camp_scores = score_tenant_from_db(db, tenant_id)
    persist_scores(db, tenant_id, emp_scores, camp_scores)
    return {"tenant_id": tenant_id, "employees_scored": len(emp_scores),
            "campaign_scores": len(camp_scores)}


@router.post("/tenants/{tenant_id}/campaigns/{campaign_id}/link")
def link_gophish_campaign(tenant_id: str, campaign_id: str,
                          req: s.LinkGoPhishRequest,
                          db: Session = Depends(get_db),
                          user: CurrentUser = Depends(require_roles("org_admin", "operator"))):
    """Associate a GoPhish campaign_id with a local campaign so inbound
    GoPhish webhook events can be mapped to it."""
    enforce_tenant(user, tenant_id)
    camp = db.query(m.Campaign).filter_by(tenant_id=tenant_id, id=campaign_id).first()
    if not camp:
        raise HTTPException(404, "campaign not found")
    camp.external_ref = req.external_ref
    _audit(db, tenant_id, user.email, "link_gophish",
           {"campaign": campaign_id, "external_ref": req.external_ref})
    db.commit()
    return {"campaign_id": campaign_id, "external_ref": req.external_ref}
