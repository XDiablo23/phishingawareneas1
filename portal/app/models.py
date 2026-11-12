"""
Portal ORM models - the portal's OWN schema (separate database from
PhishAwareness). Employees live here with their own logins; the only link
to PhishAwareness is `PortalUser.pa_employee_id` and the risk snapshot we
cache from the API. No lure content and no credentials from simulations are
ever stored here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.crypto import EncryptedSecret


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# status values for a PortalUser lifecycle
STATUS_ONBOARDING = "onboarding"   # must finish mandatory awareness first
STATUS_ACTIVE = "active"           # baseline pushed, in good standing
STATUS_REMEDIATION = "remediation" # has outstanding remediation to clear
STATUS_FLAGGED = "flagged"         # stuck elevated -> in-person + ticket raised

# module kinds
KIND_ONBOARDING = "onboarding"
KIND_REMEDIATION = "remediation"
KIND_POLICY = "policy"

# assignment reasons
REASON_ONBOARDING = "onboarding"
REASON_FAILURE = "phishing_failure"
REASON_POLICY = "new_policy"
REASON_ESCALATION = "escalation"
REASON_MANUAL = "manual"


class PortalUser(Base):
    """An employee who signs in to the portal to do training."""
    __tablename__ = "portal_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(120), default="Unassigned")
    job_title: Mapped[str] = mapped_column(String(160), default="Employee")
    seniority_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_ONBOARDING)

    # link + cached risk snapshot from PhishAwareness (for change detection)
    pa_employee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_hrs: Mapped[float] = mapped_column(Float, default=0.0)
    last_band: Mapped[str] = mapped_column(String(20), default="Low")
    last_campaigns_scored: Mapped[int] = mapped_column(Integer, default=0)
    elevated_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inperson_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")
    acks: Mapped[list["PolicyAck"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class Module(Base):
    """A training module: on-page lesson (+ optional embedded video / external
    open-source resource) gated by a minimum dwell, followed by an exam."""
    __tablename__ = "modules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default=KIND_REMEDIATION)
    level: Mapped[int] = mapped_column(Integer, default=1)  # remediation ladder
    lesson_html: Mapped[str] = mapped_column(Text, default="")
    resource_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_embed_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    min_seconds: Mapped[int] = mapped_column(Integer, default=60)
    pass_threshold: Mapped[float] = mapped_column(Float, default=0.7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    questions: Mapped[list["Question"]] = relationship(
        back_populates="module", cascade="all, delete-orphan",
        order_by="Question.order")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list] = mapped_column(JSON, nullable=False)   # list[str]
    correct_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    module: Mapped["Module"] = relationship(back_populates="questions")


class Policy(Base):
    """An org policy employees must read and agree to. Uploading a new policy
    (or a new version) can automatically assign a remediation module."""
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(40), default="1.0")
    body_html: Mapped[str] = mapped_column(Text, default="")
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    requires_ack: Mapped[bool] = mapped_column(Boolean, default=True)
    triggers_remediation: Mapped[bool] = mapped_column(Boolean, default=True)
    remediation_module_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    acks: Mapped[list["PolicyAck"]] = relationship(
        back_populates="policy", cascade="all, delete-orphan")


class PolicyAck(Base):
    __tablename__ = "policy_acks"
    __table_args__ = (UniqueConstraint("policy_id", "user_id", name="uq_ack"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    policy_id: Mapped[str] = mapped_column(ForeignKey("policies.id"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("portal_users.id"), index=True, nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    policy: Mapped["Policy"] = relationship(back_populates="acks")
    user: Mapped["PortalUser"] = relationship(back_populates="acks")


class Assignment(Base):
    """A module assigned to a user, with server-tracked dwell (watched_seconds)
    so 'non-skippable' is enforced on the server, not just the UI."""
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("portal_users.id"), index=True, nullable=False)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), default=REASON_MANUAL)
    status: Mapped[str] = mapped_column(String(20), default="assigned")  # assigned|in_progress|completed
    watched_seconds: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["PortalUser"] = relationship(back_populates="assignments")
    module: Mapped["Module"] = relationship()


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("portal_users.id"), index=True, nullable=False)
    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TicketConfig(Base):
    """Singleton: the outbound webhook to the org's ticketing system."""
    __tablename__ = "ticket_config"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="singleton")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_header_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    auth_header_value: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    system_label: Mapped[str] = mapped_column(String(80), default="Jira")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TicketLog(Base):
    __tablename__ = "ticket_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event: Mapped[str] = mapped_column(String(60), default="inperson_awareness_required")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    response_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Setting(Base):
    """Singleton: PhishAwareness connection + escalation parameters, editable
    from the admin Settings screen. NULL falls back to config.py boot values."""
    __tablename__ = "settings"
    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="singleton")
    pa_base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pa_tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Least-privilege service token issued by PhishAwareness (Manage ->
    # Integration -> rotate "portal_service_token"), scoped to only the
    # /portal signal surface - replaces a stored human operator email+
    # password, which granted this automation the full operator/admin JWT
    # blast radius. Write-only, encrypted at rest like every secret here.
    pa_service_token: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    onboarding_floor: Mapped[float | None] = mapped_column(Float, nullable=True)
    inperson_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
