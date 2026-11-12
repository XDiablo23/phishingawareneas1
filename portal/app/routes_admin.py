"""
Admin-facing portal API (prefix /api/portal/admin). Admins are the SAME people
who run PhishAwareness: they log in with their PhishAwareness credentials
(verified by delegating the login), then manage policies, training modules,
the ticketing webhook, escalation settings, and view results.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app import models as m
from app import remediation as rem
from app import pa_client as pa
from app import ticket
from app.config import settings
from app.security import make_admin_token, current_admin
from app.sanitize import sanitize_html

router = APIRouter(prefix="/api/portal/admin", tags=["admin"])

_ADMIN_ROLES = ("super_admin", "org_admin", "operator")
_POLICY_DIR = os.path.join("data", "policies")
_MAX_POLICY_BYTES = 15 * 1024 * 1024   # 15 MB cap on an uploaded policy doc
_ALLOWED_POLICY_EXT = {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf",
                       ".odt", ".html", ".htm"}


def _http_url_or_none(v):
    """Accept only http(s) URLs (blocks javascript:/data: in links & embeds)."""
    v = (v or "").strip()
    return v if v.lower().startswith(("http://", "https://")) else None


class AdminLoginIn(BaseModel):
    email: str
    password: str
    base_url: str | None = None


def _store_conn(db, base_url, tenant_id) -> None:
    """Wires which PhishAwareness backend/tenant the portal talks to - NOT a
    credential. The automation credential (pa_service_token) is configured
    separately and explicitly via PUT /settings, never derived from an
    admin's login (previously every delegated login silently overwrote the
    stored automation password with whoever last signed in)."""
    s = rem.ensure_setting(db)
    s.pa_base_url = base_url
    s.pa_tenant_id = tenant_id
    s.updated_at = datetime.now(timezone.utc)
    db.commit()


# --- admin auth (delegated to PhishAwareness) ---------------------------
@router.post("/auth/login")
def admin_login(body: AdminLoginIn, db: Session = Depends(get_db)):
    base = (body.base_url or "").strip() or None
    if not base:
        s = db.query(m.Setting).filter_by(id="singleton").first()
        base = (s.pa_base_url if s and s.pa_base_url else settings.PA_BASE_URL)
    try:
        info = pa.login_verify(base, body.email.strip(), body.password,
                               settings.PA_VERIFY_TLS)
    except pa.PAError as e:
        raise HTTPException(401, str(e))
    role = info.get("role")
    if role not in _ADMIN_ROLES:
        raise HTTPException(403, "this PhishAwareness account is not an admin/operator")
    tenant_id = info.get("tenant_id")
    # wire which PhishAwareness backend/tenant this portal talks to; the
    # automation credential itself is configured separately (see _store_conn)
    _store_conn(db, base.rstrip("/"), tenant_id)
    token = make_admin_token(body.email.strip(), tenant_id, role)
    return {"access_token": token, "token_type": "bearer",
            "admin": {"email": body.email.strip(), "role": role,
                      "tenant_id": tenant_id, "pa_base_url": base.rstrip("/")}}


# --- overview -----------------------------------------------------------
@router.get("/overview")
def overview(admin=Depends(current_admin), db: Session = Depends(get_db)):
    users = db.query(m.PortalUser).all()
    by_status: dict[str, int] = {}
    for u in users:
        by_status[u.status] = by_status.get(u.status, 0) + 1
    flagged = [{"id": u.id, "email": u.email, "full_name": u.full_name,
                "band": u.last_band, "hrs": u.last_hrs,
                "elevated_since": u.elevated_since.isoformat() if u.elevated_since else None}
               for u in users if u.inperson_escalated]
    tickets = (db.query(m.TicketLog).order_by(m.TicketLog.created_at.desc())
               .limit(5).all())
    last_sync = max((u.last_synced_at for u in users if u.last_synced_at),
                    default=None)
    return {
        "employees": len(users),
        "by_status": by_status,
        "flagged": flagged,
        "modules": db.query(m.Module).filter_by(active=True).count(),
        "policies": db.query(m.Policy).filter_by(active=True).count(),
        "recent_tickets": [{"event": t.event, "user_email": t.user_email,
                            "ok": t.ok, "status_code": t.status_code,
                            "created_at": t.created_at.isoformat() if t.created_at else None}
                           for t in tickets],
        "last_sync_at": last_sync.isoformat() if last_sync else None,
    }


# --- employees ----------------------------------------------------------
def _user_row(db, u) -> dict:
    outstanding = rem.outstanding_assignments(db, u)
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "department": u.department, "job_title": u.job_title,
        "status": u.status, "hrs": u.last_hrs, "band": u.last_band,
        "campaigns_scored": u.last_campaigns_scored,
        "pa_employee_id": u.pa_employee_id,
        "elevated_since": u.elevated_since.isoformat() if u.elevated_since else None,
        "needs_inperson": u.inperson_escalated,
        "outstanding": len(outstanding),
        "onboarded": u.onboarded_at is not None,
        "last_synced_at": u.last_synced_at.isoformat() if u.last_synced_at else None,
    }


@router.get("/employees")
def list_employees(admin=Depends(current_admin), db: Session = Depends(get_db)):
    return [_user_row(db, u) for u in
            db.query(m.PortalUser).order_by(m.PortalUser.created_at.desc()).all()]


@router.get("/employees/{user_id}")
def employee_detail(user_id: str, admin=Depends(current_admin),
                    db: Session = Depends(get_db)):
    u = db.query(m.PortalUser).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    mods = {mo.id: mo for mo in db.query(m.Module).all()}
    assignments = [{
        "id": a.id, "module": mods[a.module_id].title if a.module_id in mods else "?",
        "kind": mods[a.module_id].kind if a.module_id in mods else None,
        "reason": a.reason, "status": a.status,
        "watched_seconds": a.watched_seconds, "attempts": a.attempts,
        "best_score": round(a.best_score, 2),
    } for a in db.query(m.Assignment).filter_by(user_id=user_id).all()]
    acks = [a.policy_id for a in db.query(m.PolicyAck).filter_by(user_id=user_id).all()]
    row = _user_row(db, u)
    row.update(assignments=assignments, acknowledged_policies=acks)
    return row


class AssignIn(BaseModel):
    module_key: str
    reason: str = m.REASON_MANUAL


@router.post("/employees/{user_id}/assign")
def assign_module(user_id: str, body: AssignIn, admin=Depends(current_admin),
                  db: Session = Depends(get_db)):
    u = db.query(m.PortalUser).filter_by(id=user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    mod = db.query(m.Module).filter_by(key=body.module_key, active=True).first()
    if not mod:
        raise HTTPException(404, "module not found")
    rem.assign(db, u, mod, body.reason)
    if u.status == m.STATUS_ACTIVE and body.reason != m.REASON_ONBOARDING:
        u.status = m.STATUS_REMEDIATION
    db.commit()
    return _user_row(db, u)


@router.post("/sync")
def run_sync(admin=Depends(current_admin), db: Session = Depends(get_db)):
    """Pull each employee's PhishAwareness signal and apply the escalation
    policy (assign remediation, flag stuck users, raise tickets)."""
    return rem.sync_all(db)


# --- policies -----------------------------------------------------------
def _policy_row(db, p) -> dict:
    acks = db.query(m.PolicyAck).filter_by(policy_id=p.id).count()
    users = db.query(m.PortalUser).count()
    return {"id": p.id, "title": p.title, "version": p.version,
            "requires_ack": p.requires_ack,
            "triggers_remediation": p.triggers_remediation,
            "remediation_module_key": p.remediation_module_key,
            "file_name": p.file_name, "active": p.active,
            "acks": acks, "of_users": users,
            "created_at": p.created_at.isoformat() if p.created_at else None}


@router.get("/policies")
def admin_list_policies(admin=Depends(current_admin), db: Session = Depends(get_db)):
    return [_policy_row(db, p) for p in
            db.query(m.Policy).order_by(m.Policy.created_at.desc()).all()]


class PolicyIn(BaseModel):
    title: str
    version: str = "1.0"
    body_html: str = ""
    requires_ack: bool = True
    triggers_remediation: bool = True
    remediation_module_key: str | None = None


@router.post("/policies")
def create_policy(body: PolicyIn, admin=Depends(current_admin),
                  db: Session = Depends(get_db)):
    p = m.Policy(title=body.title, version=body.version,
                 body_html=sanitize_html(body.body_html),
                 requires_ack=body.requires_ack,
                 triggers_remediation=body.triggers_remediation,
                 remediation_module_key=body.remediation_module_key,
                 created_by=admin.get("email"))
    db.add(p)
    db.commit()
    assigned = rem.on_policy_created(db, p)
    row = _policy_row(db, p)
    row["assigned_remediation_to"] = assigned
    return row


@router.post("/policies/upload")
def upload_policy(file: UploadFile = File(...), title: str = Form(...),
                  version: str = Form("1.0"),
                  triggers_remediation: bool = Form(True),
                  remediation_module_key: str | None = Form(None),
                  admin=Depends(current_admin), db: Session = Depends(get_db)):
    os.makedirs(_POLICY_DIR, exist_ok=True)
    import re as _re
    import uuid as _uuid
    orig = os.path.basename((file.filename or "policy.bin").replace("\\", "/"))
    ext = os.path.splitext(orig)[1].lower()
    if ext not in _ALLOWED_POLICY_EXT:
        raise HTTPException(
            400, f"file type '{ext or '?'}' not allowed; use one of "
                 f"{sorted(_ALLOWED_POLICY_EXT)}")
    safe = _re.sub(r"[^A-Za-z0-9._-]", "_", orig)[:120] or "policy"
    raw = file.file.read(_MAX_POLICY_BYTES + 1)
    if len(raw) > _MAX_POLICY_BYTES:
        raise HTTPException(
            413, f"file too large (max {_MAX_POLICY_BYTES // (1024 * 1024)} MB)")
    dest = os.path.join(_POLICY_DIR, f"{_uuid.uuid4().hex}_{safe}")
    with open(dest, "wb") as f:
        f.write(raw)
    p = m.Policy(title=title, version=version, file_name=safe, file_path=dest,
                 triggers_remediation=triggers_remediation,
                 remediation_module_key=remediation_module_key,
                 body_html=f"<p>Uploaded document: <b>{safe}</b></p>",
                 created_by=admin.get("email"))
    db.add(p)
    db.commit()
    assigned = rem.on_policy_created(db, p)
    row = _policy_row(db, p)
    row["assigned_remediation_to"] = assigned
    return row


@router.delete("/policies/{policy_id}")
def deactivate_policy(policy_id: str, admin=Depends(current_admin),
                      db: Session = Depends(get_db)):
    p = db.query(m.Policy).filter_by(id=policy_id).first()
    if not p:
        raise HTTPException(404, "policy not found")
    p.active = False
    db.commit()
    return {"id": policy_id, "active": False}


# --- modules ------------------------------------------------------------
def _module_row(db, mod) -> dict:
    return {"id": mod.id, "key": mod.key, "title": mod.title, "kind": mod.kind,
            "level": mod.level, "min_seconds": mod.min_seconds,
            "pass_threshold": mod.pass_threshold, "active": mod.active,
            "questions": db.query(m.Question).filter_by(module_id=mod.id).count(),
            "resource_url": mod.resource_url,
            "video_embed_url": mod.video_embed_url}


@router.get("/modules")
def admin_list_modules(admin=Depends(current_admin), db: Session = Depends(get_db)):
    return [_module_row(db, mod) for mod in
            db.query(m.Module).order_by(m.Module.kind, m.Module.level).all()]


class QuestionIn(BaseModel):
    text: str
    choices: list[str]
    correct_index: int
    explanation: str | None = None


class ModuleIn(BaseModel):
    key: str
    title: str
    kind: str = m.KIND_REMEDIATION
    level: int = 1
    description: str = ""
    lesson_html: str = ""
    resource_url: str | None = None
    video_embed_url: str | None = None
    min_seconds: int = 60
    pass_threshold: float = 0.7
    questions: list[QuestionIn] = []


@router.post("/modules")
def create_module(body: ModuleIn, admin=Depends(current_admin),
                  db: Session = Depends(get_db)):
    if db.query(m.Module).filter_by(key=body.key).first():
        raise HTTPException(409, "a module with this key already exists")
    mod = m.Module(key=body.key, title=body.title, kind=body.kind,
                   level=body.level, description=body.description,
                   lesson_html=sanitize_html(body.lesson_html),
                   resource_url=_http_url_or_none(body.resource_url),
                   video_embed_url=_http_url_or_none(body.video_embed_url),
                   min_seconds=body.min_seconds,
                   pass_threshold=body.pass_threshold)
    db.add(mod)
    db.flush()
    for i, q in enumerate(body.questions):
        db.add(m.Question(module_id=mod.id, order=i, text=q.text,
                          choices=q.choices, correct_index=q.correct_index,
                          explanation=q.explanation))
    db.commit()
    return _module_row(db, mod)


@router.delete("/modules/{module_id}")
def deactivate_module(module_id: str, admin=Depends(current_admin),
                      db: Session = Depends(get_db)):
    mod = db.query(m.Module).filter_by(id=module_id).first()
    if not mod:
        raise HTTPException(404, "module not found")
    mod.active = False
    db.commit()
    return {"id": module_id, "active": False}


# --- ticketing integration ---------------------------------------------
class TicketConfigIn(BaseModel):
    enabled: bool = False
    webhook_url: str | None = None
    auth_header_name: str | None = None
    auth_header_value: str | None = None
    system_label: str = "Jira"


@router.get("/ticket-config")
def get_ticket_config(admin=Depends(current_admin), db: Session = Depends(get_db)):
    c = db.query(m.TicketConfig).filter_by(id="singleton").first()
    if not c:
        c = m.TicketConfig(id="singleton")
        db.add(c)
        db.commit()
    return {"enabled": c.enabled, "webhook_url": c.webhook_url,
            "auth_header_name": c.auth_header_name,
            "auth_header_set": bool(c.auth_header_value),
            "system_label": c.system_label}


@router.put("/ticket-config")
def set_ticket_config(body: TicketConfigIn, admin=Depends(current_admin),
                      db: Session = Depends(get_db)):
    c = db.query(m.TicketConfig).filter_by(id="singleton").first() or m.TicketConfig(id="singleton")
    url = (body.webhook_url or "").strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "webhook_url must be an http(s) URL")
    c.enabled = body.enabled
    c.webhook_url = url or None
    c.auth_header_name = (body.auth_header_name or "").strip() or None
    if body.auth_header_value is not None:
        c.auth_header_value = body.auth_header_value.strip() or None
    c.system_label = body.system_label or "Jira"
    c.updated_at = datetime.now(timezone.utc)
    db.add(c)
    db.commit()
    return get_ticket_config(admin, db)


@router.post("/ticket-config/test")
def test_ticket(admin=Depends(current_admin), db: Session = Depends(get_db)):
    return ticket.send_test(db)


@router.get("/tickets")
def list_tickets(admin=Depends(current_admin), db: Session = Depends(get_db)):
    rows = (db.query(m.TicketLog).order_by(m.TicketLog.created_at.desc())
            .limit(100).all())
    return [{"id": t.id, "event": t.event, "user_email": t.user_email,
             "ok": t.ok, "status_code": t.status_code,
             "response_snippet": t.response_snippet, "payload": t.payload,
             "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in rows]


# --- settings (PhishAwareness connection + escalation policy) -----------
class SettingsIn(BaseModel):
    pa_base_url: str | None = None
    pa_tenant_id: str | None = None
    pa_service_token: str | None = None
    onboarding_floor: float | None = None
    inperson_after_days: int | None = None


@router.get("/settings")
def get_settings(admin=Depends(current_admin), db: Session = Depends(get_db)):
    s = rem.ensure_setting(db)
    conn = pa.resolve_conn(db)
    return {
        "pa_base_url": conn.base_url,
        "pa_tenant_id": conn.tenant_id,
        "pa_service_token_set": bool(conn.token),
        "onboarding_floor": rem.onboarding_floor(db),
        "inperson_after_days": rem.inperson_days(db),
    }


@router.put("/settings")
def update_settings(body: SettingsIn, admin=Depends(current_admin),
                    db: Session = Depends(get_db)):
    s = rem.ensure_setting(db)
    if body.pa_base_url is not None:
        u = body.pa_base_url.strip().rstrip("/")
        if u and not u.lower().startswith(("http://", "https://")):
            raise HTTPException(400, "pa_base_url must be an http(s) URL")
        s.pa_base_url = u or None
    if body.pa_tenant_id is not None:
        s.pa_tenant_id = body.pa_tenant_id.strip() or None
    if body.pa_service_token is not None:
        s.pa_service_token = body.pa_service_token.strip() or None
    if body.onboarding_floor is not None:
        s.onboarding_floor = body.onboarding_floor
    if body.inperson_after_days is not None:
        s.inperson_after_days = body.inperson_after_days
    s.updated_at = datetime.now(timezone.utc)
    db.commit()
    return get_settings(admin, db)


@router.post("/settings/test")
def test_settings(admin=Depends(current_admin), db: Session = Depends(get_db)):
    return pa.test_connection(db)
