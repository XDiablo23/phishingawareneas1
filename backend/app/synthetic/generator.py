"""
Synthetic data generator.

Fabricates a plausible organization - employees, campaigns across all
tiers and vectors, and the interaction events those campaigns would
produce - so the scoring engine and dashboard can be exercised and
demoed end-to-end with no email, no cloning, and no external simulator.

IMPORTANT: this produces event *records* (booleans and scalars) only.
Nothing here sends mail, clones a page, or captures a real credential.
It is test-data generation, full stop.

Behavioural realism is driven by a per-employee latent "susceptibility"
and the campaign tier, so higher-tier lures fool more people and the
resulting scores form a sensible distribution.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Vector / seniority values as plain strings so this module (and scoring)
# run without the database layer. These MUST match app.db.models enums.
V_LINK = "link_only"
V_CRED = "credential_harvest"
V_ATTACH = "attachment_download"
V_CHAT = "chatbot"
V_MIXED = "mixed"

S_STAFF = "Staff"
S_MANAGER = "Manager"
S_DIRECTOR = "Director"
S_EXEC = "Exec"


DEPARTMENTS = ["Finance", "HR", "Engineering", "Sales", "IT", "Legal", "Operations"]
FIRST = ["Sara", "Omar", "Lina", "Yousef", "Rana", "Khaled", "Dana", "Tariq",
         "Maya", "Sami", "Noor", "Adam", "Hala", "Zaid", "Farah", "Bilal"]
LAST = ["Haddad", "Nasser", "Khalil", "Odeh", "Mansour", "Saleh", "Barakat",
        "Qasem", "Darwish", "Younes", "Hamdan", "Aziz", "Salti", "Rashid"]

VECTORS = [V_LINK, V_CRED, V_ATTACH, V_CHAT, V_MIXED]

SENIORITY_WEIGHTS = [
    (S_STAFF, 0.62),
    (S_MANAGER, 0.24),
    (S_DIRECTOR, 0.10),
    (S_EXEC, 0.04),
]


@dataclass
class SynEmployee:
    employee_id: str
    full_name: str
    email: str
    department: str
    job_title: str
    seniority_level: str
    manager_email: str | None
    _susceptibility: float  # latent 0..1, not persisted as a fact


@dataclass
class SynEvent:
    employee_id: str
    campaign_id: str
    event_type: str
    value: float | None = None
    breached: bool | None = None
    occurred_at: datetime | None = None


@dataclass
class SynCampaign:
    campaign_id: str
    name: str
    tier: int
    vector: str
    campaign_date: datetime
    target_ids: list[str] = field(default_factory=list)


@dataclass
class SyntheticDataset:
    tenant_name: str
    employees: list[SynEmployee]
    campaigns: list[SynCampaign]
    events: list[SynEvent]
    # (campaign_id, employee_id) -> (concrete_vector, effective_tier)
    assigned: dict[tuple[str, str], tuple[str, int]]


def _weighted_seniority(rng: random.Random) -> str:
    r = rng.random()
    acc = 0.0
    for level, w in SENIORITY_WEIGHTS:
        acc += w
        if r <= acc:
            return level
    return S_STAFF


def _concrete_vector(vector: str, rng: random.Random) -> str:
    if vector == V_MIXED:
        return rng.choice([V_LINK, V_CRED, V_ATTACH, V_CHAT])
    return vector


def _simulate_target(emp: SynEmployee, tier: int, vector: str,
                     campaign_id: str, when: datetime,
                     rng: random.Random) -> list[SynEvent]:
    """Produce the event trail for one employee in one campaign.

    Progression is gated: each deeper stage is only reachable if the
    previous one happened, with probabilities rising with susceptibility
    and falling with tier difficulty (harder lures fool fewer people, but
    those they fool tend to go deeper)."""
    events: list[SynEvent] = []

    def emit(etype, value=None, breached=None, offset_min=0):
        events.append(SynEvent(
            employee_id=emp.employee_id, campaign_id=campaign_id,
            event_type=etype, value=value, breached=breached,
            occurred_at=when + timedelta(minutes=offset_min),
        ))

    s = emp._susceptibility
    # tier realism: higher tier => more convincing => higher base engagement
    tier_pull = {1: 0.0, 2: 0.08, 3: 0.16}[tier]
    p_open = min(0.98, 0.7 + 0.25 * s)
    p_click = min(0.95, 0.15 + 0.7 * s + tier_pull)
    p_report_first = max(0.02, 0.18 * (1 - s))  # careful people report early

    if rng.random() > p_open:
        return events  # never even opened
    emit("opened", offset_min=rng.randint(1, 240))

    # a fraction report before clicking (protective)
    if rng.random() < p_report_first:
        emit("reported", offset_min=rng.randint(1, 60))
        return events

    if rng.random() > p_click:
        return events  # opened, didn't click
    emit("clicked", offset_min=rng.randint(1, 30))

    # deeper behaviour depends on vector
    if vector == V_LINK:
        pass  # click is the only signal for this vector

    elif vector == V_CRED:
        if rng.random() < 0.5 + 0.4 * s:
            emit("dwell", value=rng.randint(4, 60), offset_min=1)
        if rng.random() < 0.4 + 0.5 * s:
            emit("field_focus", offset_min=1)
            if rng.random() < 0.35 + 0.5 * s:
                if rng.random() < 0.55 + 0.35 * s:
                    breached = rng.random() < 0.35  # some reuse breached pwds
                    emit("submitted", breached=breached, offset_min=2)
                else:
                    emit("typed_no_submit", offset_min=2)

    elif vector == V_ATTACH:
        if rng.random() < 0.45 + 0.45 * s:
            emit("download", offset_min=1)

    elif vector == V_CHAT:
        if rng.random() < 0.5 + 0.4 * s:
            turns = rng.randint(1, 7)
            for i in range(turns):
                emit("chatbot_turn", offset_min=2 + i)
            if rng.random() < 0.2 + 0.5 * s:
                emit("chatbot_disclosure", offset_min=2 + turns)

    # a few report late, after engaging
    if rng.random() < 0.06 * (1 - s):
        emit("reported", offset_min=90)

    return events


def generate_dataset(
    n_employees: int = 60,
    n_campaigns: int = 8,
    seed: int | None = 42,
    tenant_name: str = "Northwind Trading Co.",
    now: datetime | None = None,
) -> SyntheticDataset:
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)

    # --- employees
    employees: list[SynEmployee] = []
    domain = "northwind.example"
    # build a few managers first so staff can point at them
    for i in range(n_employees):
        fn = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        email = f"{fn.lower().replace(' ', '.')}.{i}@{domain}"
        dept = rng.choice(DEPARTMENTS)
        level = _weighted_seniority(rng)
        title = {
            S_STAFF: f"{dept} Associate",
            S_MANAGER: f"{dept} Manager",
            S_DIRECTOR: f"Director of {dept}",
            S_EXEC: f"VP, {dept}",
        }[level]
        employees.append(SynEmployee(
            employee_id=f"emp-{i:03d}", full_name=fn, email=email,
            department=dept, job_title=title, seniority_level=level,
            manager_email=None,  # filled below
            _susceptibility=min(1.0, max(0.0, rng.betavariate(2, 3))),
        ))

    managers_by_dept: dict[str, list[str]] = {}
    for e in employees:
        if e.seniority_level in (S_MANAGER, S_DIRECTOR, S_EXEC):
            managers_by_dept.setdefault(e.department, []).append(e.email)
    for e in employees:
        if e.seniority_level == S_STAFF:
            mgrs = managers_by_dept.get(e.department)
            # ~85% of staff have a manager on file (rest test Tier-3 fallback)
            if mgrs and rng.random() < 0.85:
                e.manager_email = rng.choice(mgrs)

    # --- campaigns (spread over the last ~150 days, all tiers/vectors)
    campaigns: list[SynCampaign] = []
    assigned: dict[tuple[str, str], str] = {}
    events: list[SynEvent] = []

    for c in range(n_campaigns):
        tier = rng.choice([1, 1, 2, 2, 3])
        vector = VECTORS[c % len(VECTORS)]
        days_ago = rng.randint(2, 150)
        when = now - timedelta(days=days_ago)
        cid = f"camp-{c:02d}"
        # each campaign targets a random slice of the org
        low = min(max(3, n_employees // 3), n_employees)
        k = rng.randint(low, n_employees)
        targets = rng.sample(employees, k)
        camp = SynCampaign(campaign_id=cid,
                           name=f"{vector.replace('_', ' ').title()} - Tier {tier}",
                           tier=tier, vector=vector, campaign_date=when,
                           target_ids=[t.employee_id for t in targets])
        campaigns.append(camp)

        for emp in targets:
            # resolve concrete vector + Tier-3 fallback when no manager
            cv = _concrete_vector(vector, rng)
            eff_tier = tier
            if tier == 3 and not emp.manager_email:
                eff_tier = 2  # graceful fallback
            assigned[(cid, emp.employee_id)] = (cv, eff_tier)
            events.extend(_simulate_target(emp, eff_tier, cv, cid, when, rng))

    return SyntheticDataset(
        tenant_name=tenant_name, employees=employees,
        campaigns=campaigns, events=events, assigned=assigned,
    )
