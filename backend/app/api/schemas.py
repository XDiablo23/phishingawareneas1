"""
API request/response schemas.

Safety boundary: the event schema accepts only behavioural *metadata*.
A validator actively rejects any attempt to submit a password, secret,
or raw credential - this endpoint must never become a capture sink.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_FORBIDDEN_KEYS = {
    "password", "passwd", "pwd", "secret", "otp", "mfa_code", "token",
    "credential", "credentials", "pass", "pin", "cvv", "card",
}

EVENT_TYPES = {
    "opened", "clicked", "dwell", "field_focus", "typed_no_submit",
    "submitted", "download", "chatbot_turn", "chatbot_disclosure", "reported",
}


class EventIn(BaseModel):
    campaign_id: str
    employee_id: str
    event_type: str
    value: Optional[float] = None          # dwell seconds, etc.
    breached: Optional[bool] = None        # only for `submitted` (HIBP result)
    occurred_at: Optional[datetime] = None
    event_metadata: Optional[dict] = None

    @field_validator("event_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(f"unknown event_type '{v}'")
        return v

    @field_validator("event_metadata")
    @classmethod
    def _no_credentials(cls, v: Optional[dict]) -> Optional[dict]:
        if not v:
            return v
        for key in v:
            if str(key).strip().lower() in _FORBIDDEN_KEYS:
                raise ValueError(
                    f"credential-like field '{key}' is not accepted; this "
                    "platform never receives or stores secrets (only the "
                    "booleans `submitted` and `breached`)."
                )
        return v


class EventBatchIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list)


class IngestResult(BaseModel):
    ingested: int
    rejected: int = 0
    tenant_id: str


class CampaignScoreOut(BaseModel):
    campaign_id: str
    tier: int
    vector: str
    compromise_depth: float
    campaign_risk_severity: float
    campaign_risk_susceptibility: float
    penetration_ratio: float
    reported: bool
    breached: bool
    reasons: list[str]


class EmployeeScoreOut(BaseModel):
    employee_id: str
    full_name: str
    department: str
    seniority_level: Optional[str] = None
    hrs: float
    hrs_band: str
    susceptibility_index: float
    org_risk: float
    campaigns_scored: int
    summary: str


class SeedRequest(BaseModel):
    n_employees: int = 60
    n_campaigns: int = 8
    seed: Optional[int] = 42
    tenant_name: str = "Northwind Trading Co."


class LinkGoPhishRequest(BaseModel):
    external_ref: str  # the GoPhish campaign_id to associate with this campaign


class SeedResult(BaseModel):
    tenant_id: str
    tenant_name: str
    employees: int
    campaigns: int
    events: int
    demo_users: list[dict] = Field(default_factory=list)


# ============================================================
# Management-layer schemas (campaigns, roster, users)
# ============================================================
VALID_TIERS = {1, 2, 3}
VALID_VECTORS = {"link_only", "credential_harvest", "attachment_download", "chatbot", "mixed"}
VALID_SENIORITY = {"Staff", "Manager", "Director", "Exec"}
VALID_STATUS = {"draft", "scheduled", "running", "completed", "halted"}
VALID_ROLES = {"super_admin", "org_admin", "operator", "dept_viewer"}


# ---- campaigns ----
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tier: int
    attack_vector: str
    status: str = "draft"
    scheduled_at: Optional[datetime] = None
    external_ref: Optional[str] = None

    @field_validator("tier")
    @classmethod
    def _tier(cls, v):
        if v not in VALID_TIERS:
            raise ValueError("tier must be 1, 2, or 3")
        return v

    @field_validator("attack_vector")
    @classmethod
    def _vec(cls, v):
        if v not in VALID_VECTORS:
            raise ValueError(f"attack_vector must be one of {sorted(VALID_VECTORS)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v not in VALID_STATUS:
            raise ValueError(f"status must be one of {sorted(VALID_STATUS)}")
        return v


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    tier: Optional[int] = None
    attack_vector: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    external_ref: Optional[str] = None

    @field_validator("tier")
    @classmethod
    def _tier(cls, v):
        if v is not None and v not in VALID_TIERS:
            raise ValueError("tier must be 1, 2, or 3")
        return v

    @field_validator("attack_vector")
    @classmethod
    def _vec(cls, v):
        if v is not None and v not in VALID_VECTORS:
            raise ValueError(f"attack_vector must be one of {sorted(VALID_VECTORS)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in VALID_STATUS:
            raise ValueError(f"status must be one of {sorted(VALID_STATUS)}")
        return v


class CampaignOut(BaseModel):
    id: str
    name: str
    tier: int
    attack_vector: str
    status: str
    scheduled_at: Optional[datetime] = None
    external_ref: Optional[str] = None
    created_at: Optional[datetime] = None
    targets: int = 0
    events: int = 0


# ---- employees / roster ----
class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=200)
    department: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=160)
    manager_email: Optional[str] = None
    seniority_level: Optional[str] = None
    office_location: Optional[str] = None
    primary_tools: Optional[str] = None

    @field_validator("seniority_level")
    @classmethod
    def _sl(cls, v):
        if v not in (None, "") and v not in VALID_SENIORITY:
            raise ValueError(f"seniority_level must be one of {sorted(VALID_SENIORITY)}")
        return v or None


class EmployeeUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)
    department: Optional[str] = Field(default=None, max_length=120)
    job_title: Optional[str] = Field(default=None, max_length=160)
    manager_email: Optional[str] = None
    seniority_level: Optional[str] = None
    office_location: Optional[str] = None
    primary_tools: Optional[str] = None

    @field_validator("seniority_level")
    @classmethod
    def _sl(cls, v):
        if v not in (None, "") and v not in VALID_SENIORITY:
            raise ValueError(f"seniority_level must be one of {sorted(VALID_SENIORITY)}")
        return v


class EmployeeOut(BaseModel):
    id: str
    full_name: str
    email: str
    department: str
    job_title: str
    manager_email: Optional[str] = None
    seniority_level: Optional[str] = None
    office_location: Optional[str] = None
    primary_tools: Optional[str] = None


class ImportResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


# ---- users ----
class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str
    password: Optional[str] = None       # if omitted, a temp one is generated & returned
    department_scope: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v


class UserUpdate(BaseModel):
    role: Optional[str] = None
    department_scope: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    department_scope: Optional[str] = None
    created_at: Optional[datetime] = None


class UserCreated(UserOut):
    # returned ONCE on create / reset so the admin can share the initial password
    initial_password: Optional[str] = None


class PasswordResetResult(BaseModel):
    id: str
    email: str
    initial_password: str


# --- Self-service integration (Integration tab) --------------------------
class IntegrationConfigOut(BaseModel):
    """What the Integration tab shows. Secrets are returned masked unless
    just (re)generated, so they render once and are never re-exposed."""
    tenant_id: str
    webhook_url: str
    webhook_secret_set: bool
    ingest_token_set: bool
    beacon_url: str
    portal_service_token_set: bool = False
    webhook_secret: Optional[str] = None     # present ONLY right after rotate
    ingest_token: Optional[str] = None        # present ONLY right after rotate
    portal_service_token: Optional[str] = None  # present ONLY right after rotate


class SecretRotateRequest(BaseModel):
    field: str                                # "webhook_secret" | "ingest_token" | "portal_service_token"

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str) -> str:
        if v not in ("webhook_secret", "ingest_token", "portal_service_token"):
            raise ValueError(
                "field must be 'webhook_secret', 'ingest_token', or 'portal_service_token'")
        return v


class SecretRotateResult(BaseModel):
    tenant_id: str
    field: str                                # "webhook_secret" | "ingest_token" | "portal_service_token"
    value: str                                # the new secret, shown once


# ---- scoring settings (Manage -> Settings) ----
class ScoringSettingsOut(BaseModel):
    """Effective scoring configuration and the server defaults it inherits
    from. `source` says whether the live value is the tenant override or the
    server default, so the console can show what's actually driving scores."""
    tenant_id: str
    aggregation: str                          # effective: average | peak | blend
    blend_alpha: float                        # effective, 0..1
    aggregation_source: str                   # "tenant" | "default"
    alpha_source: str                         # "tenant" | "default"
    default_aggregation: str
    default_blend_alpha: float
    options: list[str] = ["average", "peak", "blend"]


class ScoringSettingsUpdate(BaseModel):
    """Set or clear the tenant's scoring override. Pass null for a field to
    revert it to the server default. `blend_alpha` only matters for blend."""
    aggregation: Optional[str] = None
    blend_alpha: Optional[float] = None

    @field_validator("aggregation")
    @classmethod
    def _agg(cls, v):
        if v is not None and v not in ("average", "peak", "blend"):
            raise ValueError("aggregation must be average, peak, or blend")
        return v

    @field_validator("blend_alpha")
    @classmethod
    def _alpha(cls, v):
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError("blend_alpha must be between 0 and 1")
        return v


# ---- integration health (Manage -> Integration) ----
class SourceHealth(BaseModel):
    source: str                               # "gophish" | "beacon"
    total_events: int
    events_24h: int
    last_event_at: Optional[datetime] = None
    event_types: dict[str, int] = {}


class IntegrationStatusOut(BaseModel):
    """Live connectivity view: proves from the console whether real GoPhish
    webhook and landing-beacon traffic is actually reaching the platform."""
    tenant_id: str
    webhook_secret_set: bool
    ingest_token_set: bool
    linked_campaigns: int                     # campaigns with an external_ref
    total_campaigns: int
    sources: list[SourceHealth]               # integration sources only (gophish, beacon)
    other_events: int = 0                     # seeded/synthetic events (no integration source)
    last_event_at: Optional[datetime] = None


class BeaconEventIn(BaseModel):
    """A single landing-page beacon event. The beacon posts interaction
    *metadata* only. `campaign_ref` is the GoPhish campaign id (matched to a
    linked campaign); `email` identifies the target. NO credential field is
    accepted - the same forbidden-key guard as manual ingestion applies."""
    campaign_ref: str
    email: str
    event_type: str
    value: Optional[float] = None             # dwell seconds only
    occurred_at: Optional[datetime] = None

    @field_validator("event_type")
    @classmethod
    def _beacon_allowed(cls, v: str) -> str:
        # The beacon may only emit landing-page signals - never submitted/
        # breached (those are decided server-side / by the webhook) and never
        # email-client events.
        allowed = {"opened", "clicked", "dwell", "field_focus",
                   "typed_no_submit", "download"}
        if v not in allowed:
            raise ValueError(
                f"event_type '{v}' not permitted from the beacon; allowed: "
                f"{sorted(allowed)}")
        return v


class BeaconAck(BaseModel):
    status: str
    stored: int = 0
    reason: Optional[str] = None


# ---- GoPhish sync (single-console integration) ----
class GoPhishConfigIn(BaseModel):
    """Set the tenant's GoPhish REST API connection. api_key is write-only
    (never returned); pass null/empty to leave a field unchanged is NOT the
    behaviour - omit the field to leave it, send empty string to clear it.
    verify_tls is the exception (a bool has no natural "empty" state): omit
    it to leave unchanged, send it explicitly as `null` to clear back to the
    server-wide default, or true/false to set this tenant's own override."""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    verify_tls: Optional[bool] = None


class GoPhishStatusOut(BaseModel):
    configured: bool
    base_url: str
    reachable: bool
    campaign_count: int
    error: Optional[str] = None
    api_key_set: bool = False
    verify_tls: bool = True          # effective (resolved) value actually in use
    verify_tls_override: Optional[bool] = None  # this tenant's raw setting; None = inherits the server default


class GoPhishCampaignView(BaseModel):
    id: Optional[int] = None
    name: Optional[str] = None
    status: Optional[str] = None
    launch_date: Optional[str] = None
    stats: dict = {}
    linked: bool = False


class GoPhishSyncResult(BaseModel):
    campaigns_synced: int
    employees_created: int
    events_ingested: int
    skipped_existing: int
    details: list = []
