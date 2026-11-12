"""
Employee-facing portal API (prefix /api/portal). Native sign-up/sign-in,
'my training' dashboard, non-skippable lessons (server-tracked dwell),
exams, and policy acknowledgement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app import models as m
from app import remediation as rem
from app.security import (
    hash_password, verify_password, make_employee_token, current_employee,
)

router = APIRouter(prefix="/api/portal", tags=["employee"])


class RegisterIn(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=6)
    department: str = "Unassigned"
    job_title: str = "Employee"
    seniority_level: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


def _module_brief(mod: m.Module) -> dict:
    return {"key": mod.key, "title": mod.title, "kind": mod.kind,
            "level": mod.level, "min_seconds": mod.min_seconds,
            "description": mod.description}


def _assignment_view(db, a: m.Assignment) -> dict:
    mod = a.module or db.query(m.Module).filter_by(id=a.module_id).first()
    return {
        "id": a.id, "reason": a.reason, "status": a.status,
        "watched_seconds": a.watched_seconds, "attempts": a.attempts,
        "best_score": round(a.best_score, 2),
        "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        "module": _module_brief(mod) if mod else None,
        "unlocked": a.watched_seconds >= (mod.min_seconds if mod else 0),
    }


# --- auth ---------------------------------------------------------------
@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.query(m.PortalUser).filter_by(email=email).first():
        raise HTTPException(409, "an account with this email already exists")
    user = m.PortalUser(
        email=email, full_name=body.full_name.strip(),
        department=(body.department or "Unassigned").strip(),
        job_title=(body.job_title or "Employee").strip(),
        seniority_level=body.seniority_level,
        password_hash=hash_password(body.password),
        status=m.STATUS_ONBOARDING,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # map to PhishAwareness + assign mandatory onboarding
    rem.on_register(db, user)
    return {"access_token": make_employee_token(user), "token_type": "bearer",
            "user": _me(db, user)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.query(m.PortalUser).filter_by(email=email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "incorrect email or password")
    return {"access_token": make_employee_token(user), "token_type": "bearer",
            "user": _me(db, user)}


def _me(db, user) -> dict:
    outstanding = rem.outstanding_assignments(db, user)
    unacked = rem.unacked_policies(db, user)
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "department": user.department, "job_title": user.job_title,
        "status": user.status,
        "risk": {"hrs": user.last_hrs, "band": user.last_band},
        "onboarded_at": user.onboarded_at.isoformat() if user.onboarded_at else None,
        "outstanding_count": len(outstanding),
        "unacked_policies": len(unacked),
        "needs_inperson": user.inperson_escalated,
    }


@router.get("/me")
def me(user=Depends(current_employee), db: Session = Depends(get_db)):
    return _me(db, user)


# --- training -----------------------------------------------------------
@router.get("/assignments")
def my_assignments(user=Depends(current_employee), db: Session = Depends(get_db)):
    rows = (db.query(m.Assignment).filter_by(user_id=user.id)
            .order_by(m.Assignment.assigned_at.desc()).all())
    return [_assignment_view(db, a) for a in rows]


@router.get("/assignments/{assignment_id}")
def assignment_detail(assignment_id: str, user=Depends(current_employee),
                      db: Session = Depends(get_db)):
    a = db.query(m.Assignment).filter_by(id=assignment_id, user_id=user.id).first()
    if not a:
        raise HTTPException(404, "assignment not found")
    mod = db.query(m.Module).filter_by(id=a.module_id).first()
    view = _assignment_view(db, a)
    view["module"].update({
        "lesson_html": mod.lesson_html, "resource_url": mod.resource_url,
        "video_embed_url": mod.video_embed_url,
        "pass_threshold": mod.pass_threshold,
    })
    # questions WITHOUT the correct answer
    view["questions"] = [
        {"id": q.id, "order": q.order, "text": q.text, "choices": q.choices}
        for q in mod.questions]
    return view


class HeartbeatIn(BaseModel):
    seconds: int = Field(ge=0, le=120)


@router.post("/assignments/{assignment_id}/heartbeat")
def heartbeat(assignment_id: str, body: HeartbeatIn,
              user=Depends(current_employee), db: Session = Depends(get_db)):
    a = db.query(m.Assignment).filter_by(id=assignment_id, user_id=user.id).first()
    if not a:
        raise HTTPException(404, "assignment not found")
    mod = db.query(m.Module).filter_by(id=a.module_id).first()
    if a.status == "assigned":
        a.status = "in_progress"
    # add capped dwell, never beyond what's required
    a.watched_seconds = min(mod.min_seconds, a.watched_seconds + min(body.seconds, 30))
    db.commit()
    return {"watched_seconds": a.watched_seconds, "min_seconds": mod.min_seconds,
            "unlocked": a.watched_seconds >= mod.min_seconds}


class ExamIn(BaseModel):
    answers: list[int]


@router.post("/assignments/{assignment_id}/exam")
def submit_exam(assignment_id: str, body: ExamIn,
                user=Depends(current_employee), db: Session = Depends(get_db)):
    a = db.query(m.Assignment).filter_by(id=assignment_id, user_id=user.id).first()
    if not a:
        raise HTTPException(404, "assignment not found")
    mod = db.query(m.Module).filter_by(id=a.module_id).first()
    questions = list(mod.questions)
    if a.watched_seconds < mod.min_seconds:
        raise HTTPException(409, "finish the lesson before taking the exam")
    if len(body.answers) != len(questions):
        raise HTTPException(422, f"expected {len(questions)} answers")

    correct = 0
    per_q = []
    for q, ans in zip(questions, body.answers):
        ok = (ans == q.correct_index)
        correct += 1 if ok else 0
        per_q.append({"id": q.id, "correct": ok,
                      "correct_index": q.correct_index,
                      "explanation": q.explanation})
    score = correct / len(questions) if questions else 1.0
    passed = score >= mod.pass_threshold

    a.attempts += 1
    a.best_score = max(a.best_score, score)
    db.add(m.ExamAttempt(assignment_id=a.id, user_id=user.id, module_id=mod.id,
                         score=score, passed=passed, answers=body.answers))
    newly_completed = False
    if passed and a.status != "completed":
        a.status = "completed"
        from datetime import datetime, timezone
        a.completed_at = datetime.now(timezone.utc)
        newly_completed = True
    db.commit()

    if newly_completed:
        rem.on_module_completed(db, user, a)

    return {"passed": passed, "score": round(score, 2),
            "pass_threshold": mod.pass_threshold,
            "correct": correct, "total": len(questions),
            "results": per_q, "status": a.status,
            "user": _me(db, user)}


# --- policies -----------------------------------------------------------
@router.get("/policies")
def my_policies(user=Depends(current_employee), db: Session = Depends(get_db)):
    acked = {a.policy_id: a.acknowledged_at for a in
             db.query(m.PolicyAck).filter_by(user_id=user.id).all()}
    out = []
    for p in (db.query(m.Policy).filter_by(active=True)
              .order_by(m.Policy.created_at.desc()).all()):
        out.append({
            "id": p.id, "title": p.title, "version": p.version,
            "body_html": p.body_html, "file_name": p.file_name,
            "requires_ack": p.requires_ack,
            "acknowledged": p.id in acked,
            "acknowledged_at": acked[p.id].isoformat() if p.id in acked else None,
        })
    return out


@router.post("/policies/{policy_id}/ack")
def ack_policy(policy_id: str, user=Depends(current_employee),
               db: Session = Depends(get_db)):
    p = db.query(m.Policy).filter_by(id=policy_id, active=True).first()
    if not p:
        raise HTTPException(404, "policy not found")
    existing = db.query(m.PolicyAck).filter_by(
        policy_id=policy_id, user_id=user.id).first()
    if not existing:
        db.add(m.PolicyAck(policy_id=policy_id, user_id=user.id))
        db.commit()
    return {"acknowledged": True, "policy_id": policy_id}


@router.get("/history")
def my_history(user=Depends(current_employee), db: Session = Depends(get_db)):
    rows = (db.query(m.ExamAttempt).filter_by(user_id=user.id)
            .order_by(m.ExamAttempt.attempted_at.desc()).all())
    mods = {mod.id: mod.title for mod in db.query(m.Module).all()}
    return [{"module": mods.get(r.module_id, "?"), "score": round(r.score, 2),
             "passed": r.passed,
             "attempted_at": r.attempted_at.isoformat() if r.attempted_at else None}
            for r in rows]
