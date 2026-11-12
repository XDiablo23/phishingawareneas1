"""
Management API - the operator/admin control surface.

Turns the platform from a read-only dashboard into something an org can
actually run: create and manage campaigns, maintain the employee roster
(including CSV import), and provision console users. All endpoints are
authenticated, tenant-scoped, role-gated, and audit-logged.

Role model:
  * campaigns, roster : operator + org_admin  (+ super_admin)
  * users             : org_admin             (+ super_admin)
  * CSV export        : any role (a departmental viewer's export is scoped
                        to their department)

Nothing here sends mail, generates lures, clones pages, or stores a
credential - campaigns are metadata records that link to an external
simulator (e.g. GoPhish) via `external_ref`.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import get_db
from app.db import models as m
from app.api import schemas as s
from app.api.schemas import _FORBIDDEN_KEYS
from app.api.security import (
    require_roles, enforce_tenant, dept_filter_for, hash_password,
    generate_temp_password, CurrentUser,
)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/manage", tags=["manage"])

_MANAGE = require_roles("org_admin", "operator")
_ADMIN = require_roles("org_admin")
_ANY = require_roles("org_admin", "operator", "dept_viewer")


def _audit(db, tenant_id, actor, action, detail=None):
    db.add(m.AuditLog(tenant_id=tenant_id, actor=actor, action=action, detail=detail))


def _require_tenant(db, tenant_id):
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")


def _vec(v):
    return v.value if hasattr(v, "value") else v


# ============================================================
# Campaigns
# ============================================================
def _campaign_out(db, c) -> s.CampaignOut:
    targets = db.query(m.CampaignTarget).filter_by(campaign_id=c.id).count()
    events = db.query(m.InteractionEvent).filter_by(campaign_id=c.id).count()
    return s.CampaignOut(
        id=c.id, name=c.name, tier=c.tier, attack_vector=_vec(c.attack_vector),
        status=_vec(c.status), scheduled_at=c.scheduled_at,
        external_ref=c.external_ref, created_at=c.created_at,
        targets=targets, events=events,
    )


@router.get("/campaigns", response_model=list[s.CampaignOut])
def list_campaigns(tenant_id: str, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(_ANY)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    camps = (db.query(m.Campaign).filter_by(tenant_id=tenant_id)
             .order_by(m.Campaign.created_at.desc()).all())
    return [_campaign_out(db, c) for c in camps]


@router.post("/campaigns", response_model=s.CampaignOut, status_code=201)
def create_campaign(tenant_id: str, body: s.CampaignCreate,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    c = m.Campaign(
        tenant_id=tenant_id, name=body.name, tier=body.tier,
        attack_vector=m.AttackVector(body.attack_vector),
        status=m.CampaignStatus(body.status),
        scheduled_at=body.scheduled_at, external_ref=body.external_ref,
    )
    db.add(c)
    _audit(db, tenant_id, user.email, "create_campaign", {"name": body.name})
    db.commit()
    db.refresh(c)
    return _campaign_out(db, c)


@router.patch("/campaigns/{campaign_id}", response_model=s.CampaignOut)
def update_campaign(tenant_id: str, campaign_id: str, body: s.CampaignUpdate,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    c = db.query(m.Campaign).filter_by(tenant_id=tenant_id, id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    if body.name is not None:
        c.name = body.name
    if body.tier is not None:
        c.tier = body.tier
    if body.attack_vector is not None:
        c.attack_vector = m.AttackVector(body.attack_vector)
    if body.status is not None:
        c.status = m.CampaignStatus(body.status)
    if body.scheduled_at is not None:
        c.scheduled_at = body.scheduled_at
    if body.external_ref is not None:
        c.external_ref = body.external_ref
    _audit(db, tenant_id, user.email, "update_campaign", {"id": campaign_id})
    db.commit()
    db.refresh(c)
    return _campaign_out(db, c)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(tenant_id: str, campaign_id: str,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    c = db.query(m.Campaign).filter_by(tenant_id=tenant_id, id=campaign_id).first()
    if not c:
        raise HTTPException(404, "campaign not found")
    # remove dependent rows, then the campaign
    db.query(m.InteractionEvent).filter_by(tenant_id=tenant_id, campaign_id=campaign_id).delete()
    db.query(m.CampaignTarget).filter_by(tenant_id=tenant_id, campaign_id=campaign_id).delete()
    db.query(m.CampaignScoreRow).filter_by(tenant_id=tenant_id, campaign_id=campaign_id).delete()
    db.delete(c)
    _audit(db, tenant_id, user.email, "delete_campaign", {"id": campaign_id})
    db.commit()
    return {"deleted": campaign_id, "note": "run recompute to refresh employee scores"}


# ============================================================
# Employees / roster
# ============================================================
def _emp_out(e) -> s.EmployeeOut:
    sl = e.seniority_level.value if e.seniority_level and hasattr(e.seniority_level, "value") else e.seniority_level
    return s.EmployeeOut(
        id=e.id, full_name=e.full_name, email=e.email, department=e.department,
        job_title=e.job_title, manager_email=e.manager_email, seniority_level=sl,
        office_location=e.office_location, primary_tools=e.primary_tools,
    )


@router.get("/employees", response_model=list[s.EmployeeOut])
def list_roster(tenant_id: str, db: Session = Depends(get_db),
                user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    emps = (db.query(m.Employee).filter_by(tenant_id=tenant_id)
            .order_by(m.Employee.full_name).all())
    return [_emp_out(e) for e in emps]


@router.post("/employees", response_model=s.EmployeeOut, status_code=201)
def create_employee(tenant_id: str, body: s.EmployeeCreate,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    if db.query(m.Employee).filter_by(tenant_id=tenant_id, email=body.email).first():
        raise HTTPException(409, f"an employee with email {body.email} already exists")
    e = m.Employee(
        tenant_id=tenant_id, full_name=body.full_name, email=body.email,
        department=body.department, job_title=body.job_title,
        manager_email=body.manager_email,
        seniority_level=m.SeniorityLevel(body.seniority_level) if body.seniority_level else None,
        office_location=body.office_location, primary_tools=body.primary_tools,
    )
    db.add(e)
    _audit(db, tenant_id, user.email, "create_employee", {"email": body.email})
    db.commit()
    db.refresh(e)
    return _emp_out(e)


@router.patch("/employees/{employee_id}", response_model=s.EmployeeOut)
def update_employee(tenant_id: str, employee_id: str, body: s.EmployeeUpdate,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    e = db.query(m.Employee).filter_by(tenant_id=tenant_id, id=employee_id).first()
    if not e:
        raise HTTPException(404, "employee not found")
    if body.email and body.email != e.email:
        if db.query(m.Employee).filter_by(tenant_id=tenant_id, email=body.email).first():
            raise HTTPException(409, f"email {body.email} already in use")
        e.email = body.email
    for attr in ("full_name", "department", "job_title", "manager_email",
                 "office_location", "primary_tools"):
        val = getattr(body, attr)
        if val is not None:
            setattr(e, attr, val)
    if body.seniority_level is not None:
        e.seniority_level = m.SeniorityLevel(body.seniority_level) if body.seniority_level else None
    _audit(db, tenant_id, user.email, "update_employee", {"id": employee_id})
    db.commit()
    db.refresh(e)
    return _emp_out(e)


@router.delete("/employees/{employee_id}")
def delete_employee(tenant_id: str, employee_id: str,
                    db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    e = db.query(m.Employee).filter_by(tenant_id=tenant_id, id=employee_id).first()
    if not e:
        raise HTTPException(404, "employee not found")
    db.query(m.InteractionEvent).filter_by(tenant_id=tenant_id, employee_id=employee_id).delete()
    db.query(m.CampaignTarget).filter_by(tenant_id=tenant_id, employee_id=employee_id).delete()
    db.query(m.CampaignScoreRow).filter_by(tenant_id=tenant_id, employee_id=employee_id).delete()
    db.query(m.EmployeeScoreRow).filter_by(tenant_id=tenant_id, employee_id=employee_id).delete()
    db.delete(e)
    _audit(db, tenant_id, user.email, "delete_employee", {"id": employee_id})
    db.commit()
    return {"deleted": employee_id}


@router.post("/employees/import", response_model=s.ImportResult)
async def import_roster(tenant_id: str, file: UploadFile = File(...),
                        db: Session = Depends(get_db), user: CurrentUser = Depends(_MANAGE)):
    """Bulk-load employees from CSV. Columns:
    full_name,email,department,job_title[,manager_email,seniority_level]
    Existing employees (matched by email) are updated; new ones are created.
    Credential-like columns are rejected."""
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    from app.api.uploads import read_upload_capped
    raw = (await read_upload_capped(file)).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    bad = headers & _FORBIDDEN_KEYS
    if bad:
        raise HTTPException(400, f"credential-like columns not accepted: {sorted(bad)}")
    required = {"full_name", "email", "department", "job_title"}
    if not required <= headers:
        raise HTTPException(400, f"CSV missing required columns: {sorted(required - headers)}")

    created = updated = skipped = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        try:
            # Validate through the same EmployeeCreate schema the manual
            # add-employee endpoint uses, so a CSV row is held to exactly
            # the same length caps and seniority enum as a hand-typed one -
            # this used to be a hand-rolled subset of those checks (presence
            # only, no max_length) that could silently truncate at the DB
            # column limit instead of reporting a clear per-row error.
            try:
                data = s.EmployeeCreate(
                    full_name=(row.get("full_name") or "").strip(),
                    email=(row.get("email") or "").strip(),
                    department=(row.get("department") or "").strip(),
                    job_title=(row.get("job_title") or "").strip(),
                    manager_email=(row.get("manager_email") or "").strip() or None,
                    seniority_level=(row.get("seniority_level") or "").strip() or None,
                )
            except ValidationError as ve:
                skipped += 1
                detail = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc']) or 'value'}: {e['msg']}"
                    for e in ve.errors())
                errors.append(f"row {i}: {detail}")
                continue

            existing = db.query(m.Employee).filter_by(
                tenant_id=tenant_id, email=data.email).first()
            if existing:
                existing.full_name = data.full_name
                existing.department = data.department
                existing.job_title = data.job_title
                existing.manager_email = data.manager_email
                if data.seniority_level:
                    existing.seniority_level = m.SeniorityLevel(data.seniority_level)
                updated += 1
            else:
                db.add(m.Employee(
                    tenant_id=tenant_id, full_name=data.full_name, email=data.email,
                    department=data.department, job_title=data.job_title,
                    manager_email=data.manager_email,
                    seniority_level=m.SeniorityLevel(data.seniority_level)
                    if data.seniority_level else None))
                created += 1
        except Exception as ex:  # keep going; report the row
            skipped += 1
            errors.append(f"row {i}: {type(ex).__name__}")
    _audit(db, tenant_id, user.email, "import_roster",
           {"created": created, "updated": updated, "skipped": skipped})
    db.commit()
    return s.ImportResult(created=created, updated=updated, skipped=skipped,
                          errors=errors[:50])


# ============================================================
# Users (console accounts)
# ============================================================
def _user_out(u) -> s.UserOut:
    return s.UserOut(id=u.id, email=u.email,
                     role=u.role.value if hasattr(u.role, "value") else u.role,
                     department_scope=u.department_scope, created_at=u.created_at)


@router.get("/users", response_model=list[s.UserOut])
def list_users(tenant_id: str, db: Session = Depends(get_db),
               user: CurrentUser = Depends(_ADMIN)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    users = db.query(m.User).filter_by(tenant_id=tenant_id).order_by(m.User.email).all()
    return [_user_out(u) for u in users]


@router.post("/users", response_model=s.UserCreated, status_code=201)
def create_user(tenant_id: str, body: s.UserCreate,
                db: Session = Depends(get_db), user: CurrentUser = Depends(_ADMIN)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    if db.query(m.User).filter_by(email=body.email).first():
        raise HTTPException(409, f"a user with email {body.email} already exists")
    if body.role == "super_admin":
        raise HTTPException(403, "super_admin accounts cannot be created via this endpoint")
    if body.role == "dept_viewer" and not body.department_scope:
        raise HTTPException(422, "dept_viewer requires a department_scope")
    pw = body.password or generate_temp_password()
    u = m.User(tenant_id=tenant_id, email=body.email, password_hash=hash_password(pw),
               role=m.UserRole(body.role), department_scope=body.department_scope)
    db.add(u)
    _audit(db, tenant_id, user.email, "create_user", {"email": body.email, "role": body.role})
    db.commit()
    db.refresh(u)
    out = s.UserCreated(**_user_out(u).model_dump())
    out.initial_password = pw if not body.password else None
    return out


@router.patch("/users/{user_id}", response_model=s.UserOut)
def update_user(tenant_id: str, user_id: str, body: s.UserUpdate,
                db: Session = Depends(get_db), user: CurrentUser = Depends(_ADMIN)):
    enforce_tenant(user, tenant_id)
    u = db.query(m.User).filter_by(tenant_id=tenant_id, id=user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    if body.role is not None:
        if body.role == "super_admin":
            raise HTTPException(403, "cannot elevate to super_admin here")
        u.role = m.UserRole(body.role)
    if body.department_scope is not None:
        u.department_scope = body.department_scope
    _audit(db, tenant_id, user.email, "update_user", {"id": user_id})
    db.commit()
    db.refresh(u)
    return _user_out(u)


@router.delete("/users/{user_id}")
def delete_user(tenant_id: str, user_id: str,
                db: Session = Depends(get_db), user: CurrentUser = Depends(_ADMIN)):
    enforce_tenant(user, tenant_id)
    u = db.query(m.User).filter_by(tenant_id=tenant_id, id=user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    if u.id == user.id:
        raise HTTPException(400, "you cannot delete your own account")
    db.delete(u)
    _audit(db, tenant_id, user.email, "delete_user", {"id": user_id})
    db.commit()
    return {"deleted": user_id}


@router.post("/users/{user_id}/reset-password", response_model=s.PasswordResetResult)
def reset_password(tenant_id: str, user_id: str,
                   db: Session = Depends(get_db), user: CurrentUser = Depends(_ADMIN)):
    enforce_tenant(user, tenant_id)
    u = db.query(m.User).filter_by(tenant_id=tenant_id, id=user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    pw = generate_temp_password()
    u.password_hash = hash_password(pw)
    _audit(db, tenant_id, user.email, "reset_password", {"id": user_id})
    db.commit()
    return s.PasswordResetResult(id=u.id, email=u.email, initial_password=pw)


# ============================================================
# CSV export (dept-scoped for departmental viewers)
# ============================================================
def _csv_safe(v):
    """Neutralise CSV/spreadsheet formula injection: a cell beginning with
    = + - @ (or a control char) is prefixed with a quote so Excel/Sheets treat
    it as text, not a formula."""
    if v is None:
        return ""
    s = str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@router.get("/export/employees.csv")
def export_employee_scores(tenant_id: str, db: Session = Depends(get_db),
                           user: CurrentUser = Depends(_ANY)):
    enforce_tenant(user, tenant_id)
    _require_tenant(db, tenant_id)
    dept = dept_filter_for(user)
    q = db.query(m.Employee).filter_by(tenant_id=tenant_id)
    if dept:
        q = q.filter(m.Employee.department == dept)
    emps = {e.id: e for e in q.all()}
    scores = {r.employee_id: r for r in
              db.query(m.EmployeeScoreRow).filter_by(tenant_id=tenant_id).all()}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["full_name", "email", "department", "job_title", "seniority_level",
                "hrs", "hrs_band", "susceptibility_index", "org_risk", "campaigns_scored"])
    rows = []
    for eid, e in emps.items():
        sc = scores.get(eid)
        sl = e.seniority_level.value if e.seniority_level and hasattr(e.seniority_level, "value") else e.seniority_level
        rows.append((e, sc, sl))
    rows.sort(key=lambda t: (t[1].org_risk if t[1] else 0), reverse=True)
    for e, sc, sl in rows:
        w.writerow([_csv_safe(e.full_name), _csv_safe(e.email),
                    _csv_safe(e.department), _csv_safe(e.job_title), _csv_safe(sl or ""),
                    sc.hrs if sc else "", _csv_safe(sc.hrs_band if sc else ""),
                    sc.susceptibility_index if sc else "",
                    sc.org_risk if sc else "", sc.campaigns_scored if sc else 0])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="risk_scores_{stamp}.csv"'})


# --- Self-service integration config (Integration tab) -------------------
# Surfaces the per-tenant webhook + beacon wiring so an operator can connect
# GoPhish and the landing beacon without hand-editing server config. Secrets
# live on the Tenant row (write-only): status is shown as a boolean, and the
# raw value is returned exactly once, right after a rotate.
import secrets as _secrets  # noqa: E402


def _integration_config(db, tenant_id: str,
                        new_secret: str | None = None,
                        new_token: str | None = None) -> s.IntegrationConfigOut:
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return s.IntegrationConfigOut(
        tenant_id=tenant_id,
        webhook_url=f"{base}/api/v1/integrations/gophish/webhook?tenant_id={tenant_id}",
        beacon_url=f"{base}/api/v1/integrations/beacon/events?tenant_id={tenant_id}",
        webhook_secret_set=bool(t.webhook_secret),
        ingest_token_set=bool(t.ingest_token),
        portal_service_token_set=bool(t.portal_service_token),
        webhook_secret=new_secret,
        ingest_token=new_token,
    )


@router.get("/integration", response_model=s.IntegrationConfigOut)
def get_integration(tenant_id: str, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(_MANAGE)):
    """Read the tenant's webhook + beacon URLs and secret status (never the
    secret values). Operators and admins."""
    enforce_tenant(user, tenant_id)
    return _integration_config(db, tenant_id)


@router.post("/integration/rotate", response_model=s.SecretRotateResult)
def rotate_integration_secret(tenant_id: str, body: s.SecretRotateRequest,
                              db: Session = Depends(get_db),
                              user: CurrentUser = Depends(_ADMIN)):
    """Generate a new webhook secret, beacon ingest token, or portal service
    token. The value is returned once here and stored write-only; it cannot
    be read back later. Admins only (rotating invalidates the old value
    immediately)."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    field = body.field  # already validated by SecretRotateRequest
    value = _secrets.token_urlsafe(32)
    setattr(t, field, value)
    _audit(db, tenant_id, user.email, "rotate_secret", {"field": field})
    db.commit()
    return s.SecretRotateResult(tenant_id=tenant_id, field=field, value=value)


# --- Scoring settings (Manage -> Settings) --------------------------------
# Lets an org tune the aggregation model (average / peak / blend) from the
# console instead of a redeploy. Stored on the tenant; NULL inherits the
# server default. Changing it does not rescore automatically - the console
# prompts a recompute so the effect is explicit and auditable.
from app.scoring.service import resolve_scoring_settings  # noqa: E402


@router.get("/settings", response_model=s.ScoringSettingsOut)
def get_scoring_settings(tenant_id: str, db: Session = Depends(get_db),
                         user: CurrentUser = Depends(_MANAGE)):
    """Effective scoring config + the server defaults it inherits. Operators
    and admins."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    agg, alpha = resolve_scoring_settings(t)
    return s.ScoringSettingsOut(
        tenant_id=tenant_id,
        aggregation=agg,
        blend_alpha=alpha,
        aggregation_source="tenant" if t.hrs_aggregation else "default",
        alpha_source="tenant" if t.hrs_blend_alpha is not None else "default",
        default_aggregation=settings.HRS_AGGREGATION,
        default_blend_alpha=settings.HRS_BLEND_ALPHA,
    )


@router.patch("/settings", response_model=s.ScoringSettingsOut)
def update_scoring_settings(tenant_id: str, body: s.ScoringSettingsUpdate,
                            db: Session = Depends(get_db),
                            user: CurrentUser = Depends(_ADMIN)):
    """Set or clear the tenant's scoring override. Admins only. Fields left
    out are unchanged; passing null reverts a field to the server default.
    Recompute afterwards to apply the change to stored scores."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    fields = body.model_dump(exclude_unset=True)
    if "aggregation" in fields:
        t.hrs_aggregation = fields["aggregation"]   # may be None -> inherit
    if "blend_alpha" in fields:
        t.hrs_blend_alpha = fields["blend_alpha"]
    _audit(db, tenant_id, user.email, "update_scoring_settings",
           {k: fields[k] for k in fields})
    db.commit()
    db.refresh(t)
    agg, alpha = resolve_scoring_settings(t)
    return s.ScoringSettingsOut(
        tenant_id=tenant_id,
        aggregation=agg,
        blend_alpha=alpha,
        aggregation_source="tenant" if t.hrs_aggregation else "default",
        alpha_source="tenant" if t.hrs_blend_alpha is not None else "default",
        default_aggregation=settings.HRS_AGGREGATION,
        default_blend_alpha=settings.HRS_BLEND_ALPHA,
    )


# --- Integration health (Manage -> Integration) ---------------------------
# Proves connectivity from the console: how much real GoPhish/beacon traffic
# has landed, by source, and when. Metadata only - same events the scoring
# pipeline reads; nothing here exposes a credential.
@router.get("/integration/status", response_model=s.IntegrationStatusOut)
def integration_status(tenant_id: str, db: Session = Depends(get_db),
                       user: CurrentUser = Depends(_MANAGE)):
    """Live inbound-event health by source (gophish / beacon). Operators and
    admins."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    def _as_aware(dt):
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    buckets: dict[str, dict] = {}
    overall_last = None
    for ev in db.query(m.InteractionEvent).filter_by(tenant_id=tenant_id).all():
        meta = ev.event_metadata or {}
        src = meta.get("source") or "unknown"
        b = buckets.setdefault(src, {"total": 0, "h24": 0, "last": None, "types": {}})
        b["total"] += 1
        et = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)
        b["types"][et] = b["types"].get(et, 0) + 1
        occ = _as_aware(ev.occurred_at)
        if occ is not None:
            if b["last"] is None or occ > b["last"]:
                b["last"] = occ
            if occ >= cutoff:
                b["h24"] += 1
            if overall_last is None or occ > overall_last:
                overall_last = occ

    # Always surface the two integration sources, even at zero, so the UI can
    # render a "no traffic yet" state instead of an empty list. Anything else
    # (seeded/synthetic events, which carry no integration source) is folded
    # into a single "other" count - the panel is about live integration
    # connectivity, not the demo data.
    sources = []
    for src in ("gophish", "beacon"):
        b = buckets.get(src, {"total": 0, "h24": 0, "last": None, "types": {}})
        sources.append(s.SourceHealth(
            source=src, total_events=b["total"], events_24h=b["h24"],
            last_event_at=b["last"], event_types=b["types"]))
    other_events = sum(b["total"] for src, b in buckets.items()
                       if src not in ("gophish", "beacon"))

    total_campaigns = db.query(m.Campaign).filter_by(tenant_id=tenant_id).count()
    linked = db.query(m.Campaign).filter(
        m.Campaign.tenant_id == tenant_id,
        m.Campaign.external_ref.isnot(None),
        m.Campaign.external_ref != "",
    ).count()

    return s.IntegrationStatusOut(
        tenant_id=tenant_id,
        webhook_secret_set=bool(t.webhook_secret),
        ingest_token_set=bool(t.ingest_token),
        linked_campaigns=linked,
        total_campaigns=total_campaigns,
        sources=sources,
        other_events=other_events,
        last_event_at=overall_last,
    )


# --- GoPhish sync (single front-facing console) --------------------------
# Our backend talks to GoPhish's REST API and pulls campaigns + results into
# this platform, so the org monitors and scores everything from OUR UI.
# READ-ONLY: we list/read only. Creating, launching, or sending a campaign
# stays an explicit action in GoPhish by design (keeps the deception trigger
# separate from the scorer). Submitted-form payloads are never stored.
from app.integrations import gophish_sync as _gp  # noqa: E402


@router.post("/integration/gophish/config", response_model=s.GoPhishStatusOut)
def set_gophish_config(tenant_id: str, body: s.GoPhishConfigIn,
                       db: Session = Depends(get_db), user: CurrentUser = Depends(_ADMIN)):
    """Set the tenant's GoPhish base URL, API key (write-only), and/or its
    own TLS-verification override. Admins only. Returns a fresh connection
    test."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    if body.base_url is not None:
        bu = body.base_url.strip()
        if bu and not bu.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "base_url must be an http(s) URL")
        t.gophish_base_url = bu or None
    if body.api_key is not None:
        t.gophish_api_key = body.api_key.strip() or None
    # verify_tls has no natural "empty" sentinel like the string fields
    # above, so distinguish "omitted" (leave unchanged) from "explicitly
    # sent" (set the override, `null` included) via model_fields_set.
    if "verify_tls" in body.model_fields_set:
        t.gophish_verify_tls = body.verify_tls
    _audit(db, tenant_id, user.email, "set_gophish_config",
           {"base_url": t.gophish_base_url, "api_key_set": bool(t.gophish_api_key),
            "verify_tls": t.gophish_verify_tls})
    db.commit()
    db.refresh(t)
    st = _gp.test_connection(t)
    return s.GoPhishStatusOut(api_key_set=bool(t.gophish_api_key or settings.GOPHISH_API_KEY),
                              verify_tls=_gp.resolve_conn(t)[2],
                              verify_tls_override=t.gophish_verify_tls, **st)


@router.get("/integration/gophish/status", response_model=s.GoPhishStatusOut)
def gophish_status(tenant_id: str, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(_MANAGE)):
    """Test the GoPhish connection and report reachability + campaign count."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    st = _gp.test_connection(t)
    return s.GoPhishStatusOut(api_key_set=bool(t.gophish_api_key or settings.GOPHISH_API_KEY),
                              verify_tls=_gp.resolve_conn(t)[2],
                              verify_tls_override=t.gophish_verify_tls, **st)


@router.get("/integration/gophish/campaigns", response_model=list[s.GoPhishCampaignView])
def gophish_campaigns(tenant_id: str, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(_MANAGE)):
    """Live GoPhish campaign list (id, name, status, stats, linked?) for the
    console. Read-only proxy to GoPhish."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return _gp.list_campaigns_view(t)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")


@router.post("/integration/gophish/sync", response_model=s.GoPhishSyncResult)
def gophish_sync_now(tenant_id: str, db: Session = Depends(get_db),
                     user: CurrentUser = Depends(_MANAGE)):
    """Pull GoPhish campaigns/results and reconcile into this tenant: link
    campaigns by GoPhish id, create any missing employees, ingest opened/
    clicked/submitted/reported events (metadata only). Recompute afterwards
    to fold them into HRS."""
    enforce_tenant(user, tenant_id)
    try:
        res = _gp.sync_tenant(db, tenant_id)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")
    return s.GoPhishSyncResult(**res)


# ============================================================
# Directory sync - Microsoft Entra ID (Azure AD)
# ============================================================
# Reads directory user METADATA over Microsoft Graph and upserts it into the
# roster. No user credentials are ever read or stored. Config is admin-only;
# status/preview/sync are operator+admin. All writes are audit-logged.
from app.integrations import entra as _entra  # noqa: E402


class EntraConfigIn(BaseModel):
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None


def _entra_status_dict(t) -> dict:
    return {
        "entra_tenant_id": t.entra_tenant_id or settings.ENTRA_TENANT_ID or "",
        "client_id_set": bool(t.entra_client_id or settings.ENTRA_CLIENT_ID),
        "client_secret_set": bool(t.entra_client_secret or settings.ENTRA_CLIENT_SECRET),
    }


@router.post("/integration/entra/config")
def set_entra_config(tenant_id: str, body: EntraConfigIn,
                     db: Session = Depends(get_db),
                     user: CurrentUser = Depends(_ADMIN)):
    """Set the tenant's Entra connection (tenant id, client id, client secret
    - write-only). Admins only."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    if body.tenant_id is not None:
        t.entra_tenant_id = body.tenant_id.strip() or None
    if body.client_id is not None:
        t.entra_client_id = body.client_id.strip() or None
    if body.client_secret is not None:
        t.entra_client_secret = body.client_secret.strip() or None
    _audit(db, tenant_id, user.email, "set_entra_config",
           {"tenant_id": t.entra_tenant_id, "client_id_set": bool(t.entra_client_id),
            "secret_set": bool(t.entra_client_secret)})
    db.commit()
    db.refresh(t)
    return _entra_status_dict(t)


@router.get("/integration/entra/status")
def entra_status(tenant_id: str, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(_MANAGE)):
    """Test the Entra connection (token + one user) and report config state."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    st = _entra.test_connection(t)
    st.update(_entra_status_dict(t))
    return st


@router.get("/integration/entra/preview")
def entra_preview(tenant_id: str, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(_MANAGE)):
    """A sample of directory users mapped to roster fields (no writes)."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return {"users": _entra.preview(t, limit=15)}
    except _entra.EntraError as e:
        raise HTTPException(502, f"Entra: {e}")


@router.post("/integration/entra/sync")
def entra_sync(tenant_id: str, db: Session = Depends(get_db),
               user: CurrentUser = Depends(_MANAGE)):
    """Import/refresh the roster from Entra (idempotent by email). Recompute
    afterwards to score any newly added employees."""
    enforce_tenant(user, tenant_id)
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")
    try:
        return _entra.sync_users(db, tenant_id)
    except _entra.EntraError as e:
        raise HTTPException(502, f"Entra: {e}")


# ============================================================
# GoPhish full campaign lifecycle (operator control surface)
# ============================================================
# Our console orchestrates GoPhish's REST API so the org runs everything from
# one UI. We build target GROUPS from our roster and create/launch/schedule/
# complete/delete CAMPAIGNS that reference an email template + landing page +
# sending profile the operator authored INSIDE GoPhish. We never author or
# clone lure/landing content here and never store credentials. Launch is
# authorization-gated and every write is audited.
from app.integrations import gophish_admin as _gpa  # noqa: E402


@router.get("/integration/gophish/templates")
def gophish_templates(tenant_id: str, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return _gpa.list_templates(t)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")


@router.get("/integration/gophish/pages")
def gophish_pages(tenant_id: str, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(_MANAGE)):
    """Landing pages authored in GoPhish, with their capture flags so the
    console can warn about password capture."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return _gpa.list_pages(t)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")


@router.get("/integration/gophish/smtp")
def gophish_smtp(tenant_id: str, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return _gpa.list_smtp(t)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")


@router.get("/integration/gophish/groups")
def gophish_groups(tenant_id: str, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return _gpa.list_groups(t)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")


class GroupFromRosterIn(BaseModel):
    name: str
    department: str | None = None
    employee_ids: list[str] | None = None


@router.post("/integration/gophish/groups/from-roster")
def gophish_group_from_roster(tenant_id: str, body: GroupFromRosterIn,
                              db: Session = Depends(get_db),
                              user: CurrentUser = Depends(_MANAGE)):
    """Push a GoPhish target group built from our roster (all, a department,
    or an explicit subset). Idempotent by group name."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    q = db.query(m.Employee).filter_by(tenant_id=tenant_id)
    if body.employee_ids:
        q = q.filter(m.Employee.id.in_(body.employee_ids))
    elif body.department:
        q = q.filter(m.Employee.department == body.department)
    emps = q.all()
    if not emps:
        raise HTTPException(422, "no matching employees in the roster")
    try:
        res = _gpa.push_group_from_roster(t, body.name.strip(), emps)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")
    _audit(db, tenant_id, user.email, "gophish_push_group",
           {"name": body.name, "targets": res.get("targets")})
    db.commit()
    return res


class LaunchCampaignIn(BaseModel):
    name: str
    template: str            # existing GoPhish email template (by name)
    page: str                # existing GoPhish landing page (by name)
    smtp: str                # existing GoPhish sending profile (by name)
    group: str               # GoPhish target group (by name)
    url: str                 # phishing URL GoPhish substitutes into the lure
    launch_date: str | None = None    # ISO8601; future = scheduled
    send_by_date: str | None = None
    tier: int = 2            # for OUR scoring of the linked campaign
    attack_vector: str = "credential_harvest"
    authorized: bool = False  # explicit operator authorization (required)


@router.post("/integration/gophish/campaigns/launch")
def gophish_launch_campaign(tenant_id: str, body: LaunchCampaignIn,
                            db: Session = Depends(get_db),
                            user: CurrentUser = Depends(_MANAGE)):
    """Create (launch/schedule) a GoPhish campaign referencing existing
    content, and link it to a local campaign so scoring picks up the results.
    Requires an explicit authorization confirmation."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    if not body.authorized:
        raise HTTPException(422, "authorization confirmation is required to launch a simulation")
    if body.tier not in (1, 2, 3):
        raise HTTPException(422, "tier must be 1, 2 or 3")
    try:
        vec = m.AttackVector(body.attack_vector)
    except ValueError:
        raise HTTPException(422, "invalid attack_vector")

    # Warn (never block) if the selected landing page captures passwords.
    warning = None
    try:
        pg = next((p for p in _gpa.list_pages(t) if p["name"] == body.page), None)
        if pg and pg.get("capture_passwords"):
            warning = ("The selected GoPhish landing page has 'Capture Passwords' "
                       "enabled. Best practice for awareness testing is to leave it "
                       "OFF; this platform never receives or stores those values.")
    except _gp.GoPhishError:
        pass

    try:
        res = _gpa.create_campaign(t, body.model_dump())
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")

    gid = str(res.get("id")) if res.get("id") is not None else None
    local = None
    if gid:
        local = db.query(m.Campaign).filter_by(
            tenant_id=tenant_id, external_ref=gid).first()
        if local is None:
            local = m.Campaign(
                tenant_id=tenant_id, name=body.name, tier=body.tier,
                attack_vector=vec, status=m.CampaignStatus.running,
                external_ref=gid)
            db.add(local)
            db.flush()
    _audit(db, tenant_id, user.email, "gophish_launch_campaign",
           {"name": body.name, "gophish_id": gid, "template": body.template,
            "page": body.page, "group": body.group, "authorized": True,
            "password_capture_warning": bool(warning)})
    db.commit()
    return {"gophish_id": gid, "local_campaign_id": local.id if local else None,
            "status": res.get("status"), "warning": warning}


@router.post("/integration/gophish/campaigns/{gophish_id}/complete")
def gophish_complete_campaign(tenant_id: str, gophish_id: str,
                              db: Session = Depends(get_db),
                              user: CurrentUser = Depends(_MANAGE)):
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        res = _gpa.complete_campaign(t, gophish_id)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")
    _audit(db, tenant_id, user.email, "gophish_complete_campaign",
           {"gophish_id": gophish_id})
    db.commit()
    return res


@router.delete("/integration/gophish/campaigns/{gophish_id}")
def gophish_delete_campaign(tenant_id: str, gophish_id: str,
                            db: Session = Depends(get_db),
                            user: CurrentUser = Depends(_ADMIN)):
    """Delete a campaign in GoPhish. Admins only (destructive)."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        res = _gpa.delete_campaign(t, gophish_id)
    except _gp.GoPhishError as e:
        raise HTTPException(502, f"GoPhish: {e}")
    _audit(db, tenant_id, user.email, "gophish_delete_campaign",
           {"gophish_id": gophish_id})
    db.commit()
    return {"deleted": gophish_id, "gophish": res}


# ============================================================
# Directory sync - on-prem Active Directory (LDAP)
# ============================================================
# Alternative to Entra for orgs running on-prem AD. Binds with a read-only
# service account and searches for users. Metadata only; bind password is
# write-only. Config is admin-only; status/preview/sync are operator+admin.
from app.integrations import ldap_dir as _ldap  # noqa: E402


class LdapConfigIn(BaseModel):
    uri: str | None = None
    bind_dn: str | None = None
    bind_password: str | None = None
    base_dn: str | None = None
    user_filter: str | None = None


def _ldap_status_dict(t) -> dict:
    return {
        "ldap_uri": t.ldap_uri or settings.LDAP_URI or "",
        "ldap_base_dn": t.ldap_base_dn or settings.LDAP_BASE_DN or "",
        "ldap_bind_dn": t.ldap_bind_dn or settings.LDAP_BIND_DN or "",
        "ldap_user_filter": t.ldap_user_filter or settings.LDAP_USER_FILTER,
        "bind_password_set": bool(t.ldap_bind_password or settings.LDAP_BIND_PASSWORD),
    }


@router.post("/integration/ldap/config")
def set_ldap_config(tenant_id: str, body: LdapConfigIn,
                    db: Session = Depends(get_db),
                    user: CurrentUser = Depends(_ADMIN)):
    """Set the tenant's on-prem AD (LDAP) connection. Admins only. bind
    password is write-only."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    if body.uri is not None:
        u = body.uri.strip()
        if u and not u.lower().startswith(("ldap://", "ldaps://")):
            raise HTTPException(400, "LDAP uri must start with ldap:// or ldaps://")
        t.ldap_uri = u or None
    if body.bind_dn is not None:
        t.ldap_bind_dn = body.bind_dn.strip() or None
    if body.bind_password is not None:
        t.ldap_bind_password = body.bind_password.strip() or None
    if body.base_dn is not None:
        t.ldap_base_dn = body.base_dn.strip() or None
    if body.user_filter is not None:
        t.ldap_user_filter = body.user_filter.strip() or None
    _audit(db, tenant_id, user.email, "set_ldap_config",
           {"uri": t.ldap_uri, "base_dn": t.ldap_base_dn,
            "bind_dn": t.ldap_bind_dn, "password_set": bool(t.ldap_bind_password)})
    db.commit()
    db.refresh(t)
    return _ldap_status_dict(t)


@router.get("/integration/ldap/status")
def ldap_status(tenant_id: str, db: Session = Depends(get_db),
                user: CurrentUser = Depends(_MANAGE)):
    """Test the LDAP bind + a one-user search, and report config state."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    st = _ldap.test_connection(t)
    st.update(_ldap_status_dict(t))
    return st


@router.get("/integration/ldap/preview")
def ldap_preview(tenant_id: str, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(_MANAGE)):
    """A sample of AD users mapped to roster fields (no writes)."""
    enforce_tenant(user, tenant_id)
    t = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if t is None:
        raise HTTPException(404, "tenant not found")
    try:
        return {"users": _ldap.preview(t, limit=15)}
    except _ldap.LdapError as e:
        raise HTTPException(502, f"LDAP: {e}")


@router.post("/integration/ldap/sync")
def ldap_sync(tenant_id: str, db: Session = Depends(get_db),
              user: CurrentUser = Depends(_MANAGE)):
    """Import/refresh the roster from on-prem AD (idempotent by email)."""
    enforce_tenant(user, tenant_id)
    if not db.query(m.Tenant).filter_by(id=tenant_id).first():
        raise HTTPException(404, "tenant not found")
    try:
        return _ldap.sync_users(db, tenant_id)
    except _ldap.LdapError as e:
        raise HTTPException(502, f"LDAP: {e}")
