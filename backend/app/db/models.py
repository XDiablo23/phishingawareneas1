"""
ORM models - the locked Capstone 2 schema.

Design rules honoured here:
  * `tenant_id` on EVERY tenant-scoped table (multi-tenancy is a later
    flip, not a rewrite).
  * Three-band employee schema (required / recommended / optional).
  * NO credential storage anywhere. On a submission we record only the
    booleans `submitted` (implicit as an event row) and `breached`.
    There is deliberately no password/secret column in this schema.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.crypto import EncryptedSecret


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- enums ---------------------------------------------------------------
class SeniorityLevel(str, enum.Enum):
    Staff = "Staff"
    Manager = "Manager"
    Director = "Director"
    Exec = "Exec"


class AttackVector(str, enum.Enum):
    link_only = "link_only"
    credential_harvest = "credential_harvest"
    attachment_download = "attachment_download"
    chatbot = "chatbot"
    mixed = "mixed"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    running = "running"
    completed = "completed"
    halted = "halted"


class EventType(str, enum.Enum):
    opened = "opened"
    clicked = "clicked"
    dwell = "dwell"
    field_focus = "field_focus"
    typed_no_submit = "typed_no_submit"
    submitted = "submitted"
    download = "download"
    chatbot_turn = "chatbot_turn"
    chatbot_disclosure = "chatbot_disclosure"
    reported = "reported"


class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    org_admin = "org_admin"
    operator = "operator"
    dept_viewer = "dept_viewer"


# --- tenancy -------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Self-service integration credentials (managed from the Integration tab).
    # webhook_secret: per-tenant HMAC secret for the GoPhish webhook
    #                 (falls back to the env secret, then dev-accept, if unset).
    # ingest_token:   write-only token the landing-page beacon presents to
    #                 post interaction *metadata* (never credentials).
    webhook_secret: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    ingest_token: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    # Per-tenant scoring configuration, editable from the console (Manage ->
    # Settings). NULL means "use the server default" (env HRS_AGGREGATION /
    # HRS_BLEND_ALPHA). Keeping this on the tenant lets each org tune the
    # aggregation model without a redeploy; recompute applies the change.
    hrs_aggregation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hrs_blend_alpha: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-tenant GoPhish REST API connection (Manage -> Integration -> GoPhish
    # sync). base_url points at the tenant's GoPhish admin server; api_key is
    # write-only (status shown as a boolean, value never returned). Both NULL
    # -> fall back to the server GOPHISH_API_URL / GOPHISH_API_KEY env values.
    gophish_base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    gophish_api_key: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    # NULL -> inherit the server-wide GOPHISH_VERIFY_TLS default; an explicit
    # true/false lets this tenant verify (or skip) TLS on its own GoPhish
    # server independently of every other tenant sharing this deployment.
    gophish_verify_tls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Least-privilege service token the Awareness & Remediation Portal
    # presents (header X-Portal-Token) to authenticate its automation calls
    # to the /portal surface - scoped to exactly that surface, unlike the
    # full operator/admin JWT this replaced. Write-only, rotatable, encrypted
    # at rest like every other secret column here.
    portal_service_token: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    # Microsoft Entra ID (Azure AD) directory connection (Manage -> Integration
    # -> Directory). client_secret is write-only (status shown as a boolean).
    # All NULL -> fall back to the server ENTRA_* env values. Used only to READ
    # directory user metadata into the roster; no user credentials are stored.
    entra_tenant_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entra_client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entra_client_secret: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    # On-prem Active Directory over LDAP (alternative directory source).
    # bind_password is write-only. All NULL -> fall back to the server LDAP_*
    # env values. Reads directory metadata only.
    ldap_uri: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ldap_bind_dn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ldap_bind_password: Mapped[str | None] = mapped_column(EncryptedSecret, nullable=True)
    ldap_base_dn: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ldap_user_filter: Mapped[str | None] = mapped_column(String(400), nullable=True)

    employees: Mapped[list["Employee"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan")
    campaigns: Mapped[list["Campaign"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan")


class CompanyProfile(Base):
    __tablename__ = "company_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    # required
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)
    sending_domain: Mapped[str] = mapped_column(String(200), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en")
    # optional (high value)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    brand_color: Mapped[str | None] = mapped_column(String(20))
    footer_style: Mapped[str | None] = mapped_column(Text)
    key_contacts: Mapped[dict | None] = mapped_column(JSON)  # {role: email}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CompanyEvent(Base):
    """Contextual hooks the (external) lure generator can reference."""
    __tablename__ = "company_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list | None] = mapped_column(JSON)  # ["O365 migration", ...]


# --- people --------------------------------------------------------------
class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    # hard-required
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    job_title: Mapped[str] = mapped_column(String(160), nullable=False)
    # strongly recommended (unlocks Tier 3)
    manager_email: Mapped[str | None] = mapped_column(String(200))
    seniority_level: Mapped[SeniorityLevel | None] = mapped_column(
        Enum(SeniorityLevel, native_enum=False, length=20))
    # optional enrichment
    office_location: Mapped[str | None] = mapped_column(String(160))
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_tools: Mapped[str | None] = mapped_column(String(300))
    current_projects: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # --- signals written by the Awareness & Remediation Portal (separate app) ---
    # risk_floor: a baseline HRS the score is held at-or-above (e.g. a new hire
    #   set to Moderate after onboarding, until real behaviour supersedes it).
    # needs_inperson_awareness: set when a user is stuck High/Critical too long;
    #   surfaced as a badge and used to raise an external ticket.
    risk_floor: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_inperson_awareness: Mapped[bool] = mapped_column(Boolean, default=False)
    inperson_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    inperson_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="employees")
    events: Mapped[list["InteractionEvent"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan")


# --- campaigns -----------------------------------------------------------
class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # 1,2,3
    attack_vector: Mapped[AttackVector] = mapped_column(
        Enum(AttackVector, native_enum=False, length=30), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, native_enum=False, length=20),
        default=CampaignStatus.draft)
    # optional link to an external simulator's campaign (e.g. a GoPhish
    # campaign_id) so inbound webhook events can be mapped to this campaign.
    external_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    tenant: Mapped["Tenant"] = relationship(back_populates="campaigns")
    targets: Mapped[list["CampaignTarget"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan")
    events: Mapped[list["InteractionEvent"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan")


class CampaignTarget(Base):
    """A specific employee in a campaign. `assigned_vector` resolves the
    concrete vector for 'mixed' campaigns (per-recipient randomisation)."""
    __tablename__ = "campaign_targets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    assigned_vector: Mapped[AttackVector] = mapped_column(
        Enum(AttackVector, native_enum=False, length=30), nullable=False)
    effective_tier: Mapped[int] = mapped_column(Integer, nullable=False)  # after fallback

    campaign: Mapped["Campaign"] = relationship(back_populates="targets")


# --- events (the scoring inputs) ----------------------------------------
class InteractionEvent(Base):
    """One behavioural signal. Carries only metadata - never a credential.

    `value`   : dwell seconds (for `dwell`); otherwise null.
    `breached`: only meaningful on `submitted`; result of the in-browser
                HIBP k-anonymity check. The password itself never reaches
                the server.
    """
    __tablename__ = "interaction_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, length=30), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    breached: Mapped[bool | None] = mapped_column(Boolean)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    event_metadata: Mapped[dict | None] = mapped_column(JSON)

    campaign: Mapped["Campaign"] = relationship(back_populates="events")
    employee: Mapped["Employee"] = relationship(back_populates="events")


# --- computed scores (cache of engine output) ---------------------------
class CampaignScoreRow(Base):
    __tablename__ = "campaign_scores"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    compromise_depth: Mapped[float] = mapped_column(Float, nullable=False)
    campaign_risk_severity: Mapped[float] = mapped_column(Float, nullable=False)
    campaign_risk_susceptibility: Mapped[float] = mapped_column(Float, nullable=False)
    penetration_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    reported: Mapped[bool] = mapped_column(Boolean, default=False)
    breached: Mapped[bool] = mapped_column(Boolean, default=False)
    reasons: Mapped[list | None] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EmployeeScoreRow(Base):
    __tablename__ = "employee_scores"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True, nullable=False)
    hrs: Mapped[float] = mapped_column(Float, nullable=False)
    hrs_band: Mapped[str] = mapped_column(String(20), nullable=False)
    susceptibility_index: Mapped[float] = mapped_column(Float, nullable=False)
    org_risk: Mapped[float] = mapped_column(Float, nullable=False)
    campaigns_scored: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- dashboard users (our app's own auth; NOT harvested creds) ----------
class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)  # null = super_admin
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), nullable=False)
    department_scope: Mapped[str | None] = mapped_column(String(120))  # for dept_viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# --- audit log (guardrail) ----------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
