"""
The scoring engine - the analytical heart of the platform.

Pure, dependency-free functions so the logic can be unit-tested in
isolation and reused by the API, the synthetic generator, and the
evaluation harness alike.

Pipeline (per the locked spec):

    Layer 1  Compromise Depth (CD)   cumulative per-campaign points, capped
    Layer 2  Tier coefficient (T)    r = CD * T   (severity for HRS)
    Layer 3  Decayed aggregate       HRS = sum(r*w)/sum(w), normalised to 0-100

    + Penetration ratio    (secondary)  depth reached / deepest reachable
    + Susceptibility Index (secondary)  same events, inverted tier weighting
    + Org-risk overlay     (dashboard)  HRS * role_sensitivity, kept separate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import constants as C


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
@dataclass
class Event:
    """A single interaction-event record for one target in one campaign.

    `value` carries the scalar for events that need one:
      - dwell            -> seconds on the landing page
      - chatbot_turn     -> (unused; each turn is one Event)
    `breached` is only meaningful on a `submitted` event and reflects the
    result of the in-browser HIBP k-anonymity check. The password itself
    is never present here - only this boolean.
    """
    event_type: str
    value: Optional[float] = None
    occurred_at: Optional[datetime] = None
    breached: Optional[bool] = None


@dataclass
class CampaignContext:
    """The facts about the campaign a set of events belongs to."""
    campaign_id: object
    tier: int
    vector: str                      # concrete vector (never "mixed")
    campaign_date: datetime


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
@dataclass
class CampaignScore:
    campaign_id: object
    tier: int
    vector: str
    compromise_depth: float
    tier_coefficient_severity: float
    campaign_risk_severity: float          # r = CD * T (severity)
    tier_coefficient_susceptibility: float
    campaign_risk_susceptibility: float    # r = CD * T (inverted)
    penetration_ratio: float               # 0..1
    reported: bool
    reported_before_click: bool
    breached: bool
    campaign_date: datetime
    reasons: list[str] = field(default_factory=list)


@dataclass
class EmployeeScore:
    hrs: float                             # 0..100 headline danger score
    hrs_band: str
    susceptibility_index: float            # 0..100 "how easily fooled"
    org_risk: float                        # priority weighting (may exceed 100)
    role_sensitivity: float
    campaigns_scored: int
    campaign_scores: list[CampaignScore] = field(default_factory=list)
    summary: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _band_for(score: float) -> str:
    for lo, hi, label in C.BANDS:
        if lo <= score <= hi:
            return label
    return C.BANDS[-1][2] if score > C.BANDS[-1][1] else C.BANDS[0][2]


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Layer 1 + Layer 2 : per-campaign scoring
# --------------------------------------------------------------------------
def score_campaign(events: list[Event], ctx: CampaignContext) -> CampaignScore:
    """Compute compromise depth and campaign risk for one target/campaign."""
    types = [e.event_type for e in events]
    reasons: list[str] = []

    clicked = "clicked" in types
    reported = "reported" in types
    reported_before_click = reported and not clicked

    # --- raw compromise depth (each stage counts once, except chatbot turns)
    cd = 0.0

    def add(evt_key: str, label: str):
        nonlocal cd
        cd += C.CD_POINTS[evt_key]
        reasons.append(label)

    if "opened" in types:
        add("opened", "opened the email")
    if clicked:
        add("clicked", "clicked the link")

    # dwell scores only if any dwell event exceeds the threshold
    if any(e.event_type == "dwell" and (e.value or 0) > C.DWELL_THRESHOLD_SECONDS
           for e in events):
        add("dwell_over_threshold",
            f"dwelled >{C.DWELL_THRESHOLD_SECONDS}s on the landing page")
    if "field_focus" in types:
        add("field_focus", "focused a credential field")
    if "typed_no_submit" in types and "submitted" not in types:
        add("typed_no_submit", "typed credentials without submitting")

    breached = False
    if "submitted" in types:
        add("submitted", "submitted the fake form")
        breached = any(e.event_type == "submitted" and e.breached for e in events)
        if breached:
            reasons.append("submitted password was found in a breach corpus")

    if "download" in types:
        add("download", "opened/downloaded the lure attachment")

    # chatbot: per-turn points capped, plus disclosure bonus
    turns = sum(1 for t in types if t == "chatbot_turn")
    if turns:
        pts = min(turns * C.CD_POINTS["chatbot_turn"], C.CHATBOT_TURN_CAP)
        cd += pts
        reasons.append(f"engaged the chatbot for {turns} turn(s)")
    if "chatbot_disclosure" in types:
        cd += C.CD_POINTS["chatbot_disclosure"]
        reasons.append("disclosed a secret/OTP to the chatbot")

    # cap raw depth
    cd = min(cd, C.CD_CAP)

    # --- protective / reporting adjustments
    if reported_before_click:
        cd = 0.0
        reasons = ["reported the simulation before clicking (protective)"]
    elif reported:  # reported after clicking -> dampen
        cd *= C.REPORTED_AFTER_CLICK_MULTIPLIER
        reasons.append("later reported the simulation (partial credit)")

    # --- Layer 2: tier coefficients
    t_sev = C.TIER_SEVERITY.get(ctx.tier, 1.0)
    t_sus = C.TIER_SUSCEPTIBILITY.get(ctx.tier, 1.0)

    if reported_before_click:
        r_sev = C.PROTECTIVE_CREDIT_R      # small negative pull on the aggregate
        r_sus = 0.0                        # not susceptible at all
    else:
        r_sev = cd * t_sev
        r_sus = cd * t_sus

    # --- penetration ratio (uses the concrete vector's reachable ceiling)
    ceiling = C.vector_max_depth(ctx.vector)
    penetration = 0.0 if ceiling <= 0 else max(0.0, min(cd / ceiling, 1.0))

    if not reasons:
        reasons = ["no interaction recorded"]

    return CampaignScore(
        campaign_id=ctx.campaign_id,
        tier=ctx.tier,
        vector=ctx.vector,
        compromise_depth=round(cd, 2),
        tier_coefficient_severity=t_sev,
        campaign_risk_severity=round(r_sev, 2),
        tier_coefficient_susceptibility=t_sus,
        campaign_risk_susceptibility=round(r_sus, 2),
        penetration_ratio=round(penetration, 3),
        reported=reported,
        reported_before_click=reported_before_click,
        breached=breached,
        campaign_date=_as_utc(ctx.campaign_date),
        reasons=reasons,
    )


# --------------------------------------------------------------------------
# Layer 3 : decayed aggregate across a target's campaigns
# --------------------------------------------------------------------------
def _decay_weight(campaign_date: datetime, as_of: datetime) -> float:
    age_days = (as_of - _as_utc(campaign_date)).total_seconds() / 86400.0
    age_days = max(age_days, 0.0)
    return 0.5 ** (age_days / C.DECAY_HALF_LIFE_DAYS)


def score_employee(
    campaign_scores: list[CampaignScore],
    seniority_level: Optional[str] = None,
    as_of: Optional[datetime] = None,
    aggregation: str = "average",
    blend_alpha: float = 0.5,
) -> EmployeeScore:
    """Aggregate per-campaign risk into HRS, susceptibility, and org risk.

    Per-campaign risk r = CD * tier is capped at 100 (the band scale); each
    campaign's *residual* today is r*w after decay.

    `aggregation` selects how the headline HRS combines the residuals:
      - "average": sum(r*w) / max(sumw, 1) - decayed mean with an evidence
        floor, so sparse/stale history fades in absolute terms.
      - "peak": the single worst residual - one bad failure stands out,
        but it too fades with age.
      - "blend" (service default): alpha*peak + (1-alpha)*average - the
        headline reflects the worst recent behaviour without letting one
        event mask (or be masked by) the track record.
    The susceptibility index always uses the floored weighted mean.
    """
    as_of = _as_utc(as_of or datetime.now(timezone.utc))
    role_sensitivity = C.ROLE_SENSITIVITY.get(
        seniority_level or "", C.DEFAULT_ROLE_SENSITIVITY
    )

    if not campaign_scores:
        return EmployeeScore(
            hrs=0.0, hrs_band=_band_for(0.0), susceptibility_index=0.0,
            org_risk=0.0, role_sensitivity=role_sensitivity,
            campaigns_scored=0, campaign_scores=[],
            summary="No campaigns scored yet.",
        )

    num = num_sus = den = 0.0
    residuals: list[float] = []
    for cs in campaign_scores:
        w = _decay_weight(cs.campaign_date, as_of)
        nr = min(cs.campaign_risk_severity, C.CAMPAIGN_RISK_CAP)
        ns = min(cs.campaign_risk_susceptibility, C.CAMPAIGN_RISK_CAP)
        residuals.append(nr * w)          # this campaign's risk *today*
        num += nr * w
        num_sus += ns * w
        den += w

    # Evidence floor: sumw below 1 is treated as 1, so sparse/stale history
    # fades in absolute terms instead of a lone old failure scoring as if
    # it happened yesterday (the ratio would otherwise cancel the weight).
    den_f = max(den, C.EVIDENCE_FLOOR)

    hrs_average = max(0.0, min(num / den_f, 100.0))
    # Peak = the worst *decayed residual*, i.e. the single most damaging
    # campaign as it stands today. It fades with age like everything else;
    # when the worst failure is old and sparse it can sit below the average
    # - that is intended (the residue is spread, not spiking).
    hrs_peak = max(0.0, min(max(residuals), 100.0))

    mode = (aggregation or "average").lower()
    if mode == "peak":
        hrs = hrs_peak
    elif mode == "blend":
        a = min(max(blend_alpha, 0.0), 1.0)
        hrs = a * hrs_peak + (1 - a) * hrs_average
    else:
        hrs = hrs_average
    hrs = max(0.0, min(hrs, 100.0))

    susceptibility = max(0.0, min(num_sus / den_f, 100.0))
    org_risk = hrs * role_sensitivity

    band = _band_for(hrs)
    worst = max(campaign_scores, key=lambda c: c.campaign_risk_severity)
    summary = (
        f"HRS {hrs:.0f}/100 ({band}); susceptibility {susceptibility:.0f}/100 "
        f"across {len(campaign_scores)} campaign(s). "
        f"Most damaging: Tier-{worst.tier} {worst.vector} "
        f"(depth {worst.compromise_depth:.0f})."
    )

    return EmployeeScore(
        hrs=round(hrs, 1),
        hrs_band=band,
        susceptibility_index=round(susceptibility, 1),
        org_risk=round(org_risk, 1),
        role_sensitivity=role_sensitivity,
        campaigns_scored=len(campaign_scores),
        campaign_scores=list(campaign_scores),
        summary=summary,
    )
