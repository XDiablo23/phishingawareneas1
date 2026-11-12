"""
Central, tunable scoring parameters.

Every number the scoring engine uses lives here so the model can be
re-calibrated without touching logic. Values match the locked Capstone 2
specification (severity tier weighting; 90-day decay half-life).

NOTE ON SAFETY SCOPE
--------------------
This module - and this entire codebase - is the *measurement* layer only.
It ingests interaction-event metadata (clicked / dwelled / submitted /
reported, as booleans and scalars) and produces risk analytics. It does
NOT generate lures, clone pages, capture credentials, or send anything.
No password value is ever accepted or stored anywhere in this system
(see the credential-handling policy: only the booleans `submitted` and
`breached` are ever recorded).
"""

from __future__ import annotations

# --- Layer 1: Compromise Depth (CD) point values -------------------------
# Cumulative points for each stage a target reaches within one campaign.
CD_POINTS = {
    "opened": 2,                 # email open - unreliable over real inboxes, low weight
    "clicked": 15,               # clicked the link
    "dwell_over_threshold": 5,   # landed and dwelled beyond DWELL_THRESHOLD_SECONDS
    "field_focus": 5,            # focused a credential field
    "typed_no_submit": 10,       # typed into a field without submitting
    "submitted": 30,             # submitted the fake form
    "download": 15,              # opened / "downloaded" a lure attachment or secondary link
    "chatbot_turn": 8,           # per meaningful chatbot turn (capped, see below)
    "chatbot_disclosure": 15,    # disclosed a secret / OTP in the chatbot
}

DWELL_THRESHOLD_SECONDS = 10     # dwell must exceed this to score
CHATBOT_TURN_CAP = 30            # max total points from chatbot turns
CD_CAP = 100                     # a single campaign cannot exceed this depth

# --- Protective (reporting) behaviour ------------------------------------
# Reporting a simulation is good behaviour and must move the score the
# right way. Reporting before any click zeroes the compromise and applies
# a small negative "protective credit" that pulls the decayed aggregate
# down. Reporting after clicking dampens the accumulated depth.
REPORTED_AFTER_CLICK_MULTIPLIER = 0.4
PROTECTIVE_CREDIT_R = -10.0      # applied as the campaign's severity risk when reported pre-click

# --- Layer 2: tier difficulty coefficients -------------------------------
# SEVERITY view (chosen): falling for the hardest, most realistic attack
# is the most dangerous, so Tier 3 carries the highest coefficient. This
# drives the headline HRS.
TIER_SEVERITY = {1: 1.0, 2: 1.3, 3: 1.6}

# INVERTED view: being fooled by an *easy* lure signals higher
# susceptibility, so Tier 1 carries the highest coefficient. This drives
# the secondary Susceptibility Index over the same events.
TIER_SUSCEPTIBILITY = {1: 1.4, 2: 1.2, 3: 1.0}

# --- Layer 3: decay + normalisation --------------------------------------
DECAY_HALF_LIFE_DAYS = 90        # w = 0.5 ** (age_days / half_life)

# Normalisation: campaign risk r = CD * tier lands directly on the 0-100
# band scale, capped at the scale itself. The tier coefficient accelerates
# mid-range failures toward the cap (click on T3 27.2 vs T1 17); a full
# compromise is Critical on ANY tier. (The previous model divided by the
# theoretical ceiling CD_CAPx1.6=160, which compressed a Tier-3 credential
# submit to 57 and a Tier-1 submit to 36 - bands stopped meaning what they
# said. See docs/Administration.md "Calibration".)
CAMPAIGN_RISK_CAP = 100.0

# Aggregation evidence floor: when the decayed weight mass sumw is below this,
# the denominator is floored here, so a lone stale failure fades toward 0
# instead of holding its full value forever (a weighted MEAN cancels the
# weight for a single campaign; the floor restores absolute decay).
EVIDENCE_FLOOR = 1.0

# Score bands over the normalised 0-100 HRS.
BANDS = [
    (0, 24, "Low"),
    (25, 49, "Moderate"),
    (50, 74, "High"),
    (75, 100, "Critical"),
]

# --- Org-risk overlay ----------------------------------------------------
# Priority multiplier by seniority. Kept SEPARATE from the individual HRS:
# it helps an admin prioritise (an exec who fails is a bigger org problem
# than an intern who fails) without penalising a person for their title.
ROLE_SENSITIVITY = {
    "Exec": 2.0,
    "Director": 1.6,
    "Manager": 1.3,
    "Staff": 1.0,
}
DEFAULT_ROLE_SENSITIVITY = 1.0

# --- Attack vectors ------------------------------------------------------
VECTORS = ("link_only", "credential_harvest", "attachment_download", "chatbot", "mixed")

# Which event types each vector can actually produce. Used to compute the
# penetration ratio (how far a target went relative to how far this vector
# could take them). "mixed" is resolved per-target to a concrete vector
# before scoring, so it is not scored directly.
VECTOR_REACHABLE_EVENTS = {
    "link_only": ["opened", "clicked"],
    "credential_harvest": [
        "opened", "clicked", "dwell_over_threshold",
        "field_focus", "typed_no_submit", "submitted",
    ],
    "attachment_download": ["opened", "clicked", "download"],
    "chatbot": ["opened", "clicked", "chatbot_turn", "chatbot_disclosure"],
}


def vector_max_depth(vector: str) -> float:
    """Deepest compromise depth reachable for a given (concrete) vector."""
    events = VECTOR_REACHABLE_EVENTS.get(vector)
    if not events:
        # Fallback: treat unknown/mixed as full reachable depth.
        return float(CD_CAP)
    total = 0.0
    for ev in events:
        if ev == "chatbot_turn":
            total += CHATBOT_TURN_CAP        # turns cap, not single-turn value
        else:
            total += CD_POINTS[ev]
    return float(min(total, CD_CAP))
