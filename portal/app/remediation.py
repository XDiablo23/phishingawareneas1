"""
The remediation / escalation engine - the automatic policy that ties the
portal to PhishAwareness:

  sign-up            -> map to PhishAwareness + assign mandatory onboarding
  onboarding done    -> push a MODERATE baseline floor to PhishAwareness
  phishing failure   -> assign remediation (a ladder: standard -> extended)
  new org policy     -> assign remediation to everyone + require acknowledgement
  stuck High/Critical-> mark 'needs in-person awareness' in PhishAwareness AND
                        raise a ticket to the org's ticketing system

Everything here is idempotent and safe to run repeatedly (the sync loop calls
it on a schedule).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models as m
from app import pa_client as pa
from app import ticket
from app.config import settings

_BAND_RANK = {"Low": 0, "Moderate": 1, "High": 2, "Critical": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _band_rank(b: str) -> int:
    return _BAND_RANK.get(b or "Low", 0)


def ensure_setting(db) -> m.Setting:
    s = db.query(m.Setting).filter_by(id="singleton").first()
    if s is None:
        s = m.Setting(id="singleton")
        db.add(s)
        db.commit()
    return s


def onboarding_floor(db) -> float:
    s = ensure_setting(db)
    return float(s.onboarding_floor if s.onboarding_floor is not None
                 else settings.ONBOARDING_FLOOR)


def inperson_days(db) -> int:
    s = ensure_setting(db)
    return int(s.inperson_after_days if s.inperson_after_days is not None
               else settings.INPERSON_AFTER_DAYS)


# --- assignment helpers --------------------------------------------------
def _active_assignment(db, user, module_id):
    return (db.query(m.Assignment)
            .filter(m.Assignment.user_id == user.id,
                    m.Assignment.module_id == module_id,
                    m.Assignment.status != "completed")
            .first())


def assign(db, user, module, reason) -> m.Assignment:
    """Assign a module unless the user already has it open (idempotent)."""
    existing = _active_assignment(db, user, module.id)
    if existing:
        return existing
    a = m.Assignment(user_id=user.id, module_id=module.id, reason=reason)
    db.add(a)
    db.flush()
    return a


def outstanding_assignments(db, user) -> list[m.Assignment]:
    return (db.query(m.Assignment)
            .filter(m.Assignment.user_id == user.id,
                    m.Assignment.status != "completed").all())


def unacked_policies(db, user) -> list[m.Policy]:
    acked = {a.policy_id for a in
             db.query(m.PolicyAck).filter_by(user_id=user.id).all()}
    return [p for p in db.query(m.Policy).filter_by(active=True, requires_ack=True).all()
            if p.id not in acked]


def _apply_snapshot(user, sig: dict) -> None:
    user.last_hrs = float(sig.get("hrs") or 0.0)
    user.last_band = sig.get("hrs_band") or "Low"
    user.last_campaigns_scored = int(sig.get("campaigns_scored") or 0)
    if sig.get("employee_id"):
        user.pa_employee_id = sig["employee_id"]


def _onboarding_modules(db):
    return (db.query(m.Module)
            .filter_by(kind=m.KIND_ONBOARDING, active=True)
            .order_by(m.Module.level).all())


# --- lifecycle: sign-up + onboarding ------------------------------------
def on_register(db, user) -> None:
    """First sign-up: map to PhishAwareness and assign mandatory onboarding.
    The user cannot become 'active' until onboarding is complete."""
    try:
        sig = pa.ensure_employee(
            db, user.email, user.full_name, user.department,
            user.job_title, user.seniority_level)
        _apply_snapshot(user, sig)
    except pa.PAError:
        pass  # portal still works offline; mapping retried on next sync
    for mod in _onboarding_modules(db):
        assign(db, user, mod, m.REASON_ONBOARDING)
    user.status = m.STATUS_ONBOARDING
    db.commit()


def _all_onboarding_done(db, user) -> bool:
    ob = (db.query(m.Assignment)
          .filter_by(user_id=user.id, reason=m.REASON_ONBOARDING).all())
    return bool(ob) and all(a.status == "completed" for a in ob)


def _complete_onboarding(db, user) -> None:
    user.onboarded_at = _now()
    if user.status == m.STATUS_ONBOARDING:
        user.status = m.STATUS_ACTIVE
    # push the MODERATE baseline into PhishAwareness
    if user.pa_employee_id:
        try:
            sig = pa.set_risk_floor(db, user.pa_employee_id, onboarding_floor(db))
            _apply_snapshot(user, sig)
        except pa.PAError:
            pass
    db.commit()


def _maybe_clear_remediation(db, user) -> None:
    rem = [a for a in outstanding_assignments(db, user)
           if a.reason in (m.REASON_FAILURE, m.REASON_POLICY, m.REASON_ESCALATION)]
    if not rem and user.status == m.STATUS_REMEDIATION:
        user.status = m.STATUS_ACTIVE
        db.commit()


def on_module_completed(db, user, assignment) -> None:
    """Called when an assignment is freshly marked completed (dwell + exam)."""
    if assignment.reason == m.REASON_ONBOARDING or user.status == m.STATUS_ONBOARDING:
        if _all_onboarding_done(db, user):
            _complete_onboarding(db, user)
    _maybe_clear_remediation(db, user)


# --- policy uploads ------------------------------------------------------
def _default_policy_module(db):
    mod = db.query(m.Module).filter_by(kind=m.KIND_POLICY, active=True).first()
    if mod:
        return mod
    return (db.query(m.Module)
            .filter_by(kind=m.KIND_REMEDIATION, active=True)
            .order_by(m.Module.level).first())


def on_policy_created(db, policy) -> int:
    """A new policy (or version) is uploaded: everyone must acknowledge it, and
    (if configured) everyone is assigned a remediation module to re-train."""
    if not policy.triggers_remediation:
        db.commit()
        return 0
    mod = None
    if policy.remediation_module_key:
        mod = (db.query(m.Module)
               .filter_by(key=policy.remediation_module_key, active=True).first())
    mod = mod or _default_policy_module(db)
    n = 0
    if mod:
        for user in db.query(m.PortalUser).all():
            assign(db, user, mod, m.REASON_POLICY)
            if user.status == m.STATUS_ACTIVE:
                user.status = m.STATUS_REMEDIATION
            n += 1
    db.commit()
    return n


# --- failure ladder ------------------------------------------------------
def _next_remediation_module(db, user):
    """The remediation ladder: first not-yet-completed level; if the user has
    an open one already, keep it; if all levels are done, repeat the deepest
    (the 'extended' module) for a persistent re-offender."""
    completed = {a.module_id for a in db.query(m.Assignment)
                 .filter_by(user_id=user.id, status="completed").all()}
    ladder = (db.query(m.Module)
              .filter_by(kind=m.KIND_REMEDIATION, active=True)
              .order_by(m.Module.level).all())
    if not ladder:
        return None
    for mod in ladder:
        open_a = _active_assignment(db, user, mod.id)
        if open_a:
            return mod            # already working this level
        if mod.id not in completed:
            return mod            # next fresh level
    return ladder[-1]             # all done -> repeat the deepest


# --- in-person escalation ------------------------------------------------
def _escalate_inperson(db, user, days: int) -> None:
    reason = (f"Stuck {user.last_band} for {days} days despite automated "
              f"remediation (HRS {user.last_hrs}).")
    if user.pa_employee_id:
        try:
            pa.set_inperson_flag(db, user.pa_employee_id, True, reason)
        except pa.PAError:
            pass
    user.inperson_escalated = True
    user.status = m.STATUS_FLAGGED
    ticket.raise_inperson_ticket(db, user, days, reason)


def _deescalate_inperson(db, user) -> None:
    if user.pa_employee_id:
        try:
            pa.set_inperson_flag(db, user.pa_employee_id, False, None)
        except pa.PAError:
            pass
    user.inperson_escalated = False
    if user.status == m.STATUS_FLAGGED:
        user.status = m.STATUS_ACTIVE


# --- the sync: pull PA signal, apply the whole policy --------------------
def sync_user(db, user, now: datetime | None = None) -> dict:
    now = now or _now()
    res = {"email": user.email, "actions": []}
    try:
        sig = pa.get_by_email(db, user.email)
    except pa.PAError as e:
        user.last_synced_at = now
        db.commit()
        res["actions"].append(f"pa_unreachable")
        res["error"] = str(e)
        return res

    prev_camps = user.last_campaigns_scored
    prev_band = user.last_band
    _apply_snapshot(user, sig)
    band = user.last_band
    elevated = band in ("High", "Critical")
    new_activity = user.last_campaigns_scored > prev_camps
    worsened = _band_rank(band) > _band_rank(prev_band)

    # a fresh failure (new scored campaign, or band climbed) while elevated
    if elevated and (new_activity or worsened):
        mod = _next_remediation_module(db, user)
        if mod:
            assign(db, user, mod, m.REASON_FAILURE)
            if user.status == m.STATUS_ACTIVE:
                user.status = m.STATUS_REMEDIATION
            res["actions"].append(f"remediation:{mod.key}")

    # elevated-duration tracking -> in-person + ticket
    if elevated:
        if user.elevated_since is None:
            user.elevated_since = now
        days = (now - _aware(user.elevated_since)).days
        if days >= inperson_days(db) and not user.inperson_escalated:
            _escalate_inperson(db, user, days)
            res["actions"].append("inperson_escalated")
    else:
        if user.elevated_since is not None:
            user.elevated_since = None
        if user.inperson_escalated:
            _deescalate_inperson(db, user)
            res["actions"].append("inperson_cleared")

    user.last_synced_at = now
    db.commit()
    res.update(hrs=user.last_hrs, band=band, status=user.status)
    return res


def sync_all(db, now: datetime | None = None) -> dict:
    now = now or _now()
    users = db.query(m.PortalUser).all()
    results = [sync_user(db, u, now) for u in users]
    changed = [r for r in results if r.get("actions") and
               r["actions"] != ["pa_unreachable"]]
    return {"synced": len(results), "changed": len(changed), "results": results}
