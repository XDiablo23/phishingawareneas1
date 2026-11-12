"""
Scoring-engine unit tests.

Doubles as the first half of the 'score sanity' evaluation from the spec:
scripted scenarios with an expected ordering, asserting the engine
produces monotonic, explainable outputs consistent with the SEVERITY
weighting the team chose.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.scoring import (
    Event, CampaignContext, score_campaign, score_employee,
)
from app.scoring import constants as C

NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def ctx(tier, vector, days_ago=0, cid="c"):
    return CampaignContext(
        campaign_id=cid, tier=tier, vector=vector,
        campaign_date=NOW - timedelta(days=days_ago),
    )


# --- Layer 1: compromise depth ------------------------------------------
def test_no_interaction_is_zero():
    cs = score_campaign([], ctx(1, "credential_harvest"))
    assert cs.compromise_depth == 0
    assert cs.penetration_ratio == 0
    assert "no interaction" in cs.reasons[0]


def test_full_credential_compromise_depth():
    events = [
        Event("opened"), Event("clicked"),
        Event("dwell", value=30), Event("field_focus"),
        Event("typed_no_submit"), Event("submitted", breached=True),
    ]
    cs = score_campaign(events, ctx(1, "credential_harvest"))
    # 2 + 15 + 5 + 5 + (typed suppressed by submit) + 30 = 57
    assert cs.compromise_depth == 57
    assert cs.breached is True
    assert any("breach" in r for r in cs.reasons)


def test_typed_suppressed_when_submitted():
    with_typed = score_campaign(
        [Event("clicked"), Event("typed_no_submit"), Event("submitted")],
        ctx(1, "credential_harvest"),
    )
    without_typed = score_campaign(
        [Event("clicked"), Event("submitted")],
        ctx(1, "credential_harvest"),
    )
    assert with_typed.compromise_depth == without_typed.compromise_depth


def test_dwell_below_threshold_does_not_score():
    below = score_campaign([Event("clicked"), Event("dwell", value=5)],
                           ctx(1, "credential_harvest"))
    assert below.compromise_depth == C.CD_POINTS["clicked"]


def test_chatbot_turns_capped():
    events = [Event("clicked")] + [Event("chatbot_turn") for _ in range(20)]
    cs = score_campaign(events, ctx(1, "chatbot"))
    # clicked 15 + capped chatbot 30 = 45
    assert cs.compromise_depth == 15 + C.CHATBOT_TURN_CAP


def test_depth_capped_at_100():
    events = [
        Event("opened"), Event("clicked"), Event("dwell", value=99),
        Event("field_focus"), Event("typed_no_submit"),
        Event("submitted"), Event("download"),
    ] + [Event("chatbot_turn") for _ in range(10)] + [Event("chatbot_disclosure")]
    cs = score_campaign(events, ctx(3, "mixed"))
    assert cs.compromise_depth <= C.CD_CAP


# --- Reporting (protective) ---------------------------------------------
def test_report_before_click_zeroes_and_protects():
    cs = score_campaign([Event("reported")], ctx(3, "credential_harvest"))
    assert cs.compromise_depth == 0
    assert cs.reported_before_click is True
    assert cs.campaign_risk_severity == C.PROTECTIVE_CREDIT_R
    assert cs.campaign_risk_susceptibility == 0


def test_report_after_click_dampens():
    no_report = score_campaign(
        [Event("clicked"), Event("submitted")], ctx(1, "credential_harvest"))
    with_report = score_campaign(
        [Event("clicked"), Event("submitted"), Event("reported")],
        ctx(1, "credential_harvest"))
    assert with_report.compromise_depth == pytest.approx(
        no_report.compromise_depth * C.REPORTED_AFTER_CLICK_MULTIPLIER)


# --- Penetration ratio ---------------------------------------------------
def test_penetration_ratio_link_only_full():
    # link_only ceiling = opened(2)+clicked(15)=17; full click+open -> 1.0
    cs = score_campaign([Event("opened"), Event("clicked")], ctx(1, "link_only"))
    assert cs.penetration_ratio == 1.0


def test_penetration_ratio_partial_on_credential():
    # same click-only behaviour on a credential vector -> far from ceiling
    cs = score_campaign([Event("opened"), Event("clicked")],
                        ctx(1, "credential_harvest"))
    assert cs.penetration_ratio < 0.5


# --- Layer 2: severity weighting ordering --------------------------------
def test_tier_severity_ordering_same_depth():
    events = [Event("clicked"), Event("submitted")]
    r1 = score_campaign(events, ctx(1, "credential_harvest")).campaign_risk_severity
    r2 = score_campaign(events, ctx(2, "credential_harvest")).campaign_risk_severity
    r3 = score_campaign(events, ctx(3, "credential_harvest")).campaign_risk_severity
    assert r1 < r2 < r3  # severity: higher tier hurts more at equal depth


def test_susceptibility_inverts_tier():
    events = [Event("clicked"), Event("submitted")]
    s1 = score_campaign(events, ctx(1, "credential_harvest")).campaign_risk_susceptibility
    s3 = score_campaign(events, ctx(3, "credential_harvest")).campaign_risk_susceptibility
    assert s1 > s3  # fooled by an easy lure => more susceptible


# --- SANITY: the canonical cross-scenario ordering -----------------------
def test_sanity_submitted_low_tier_outranks_clicked_high_tier():
    """Per the chosen severity model (depth already encodes severity):
    someone who SUBMITTED creds to a Tier-1 lure is more dangerous (higher
    HRS) than someone who only CLICKED a Tier-3 lure."""
    submitted_t1 = score_employee(
        [score_campaign(
            [Event("opened"), Event("clicked"), Event("dwell", value=20),
             Event("field_focus"), Event("submitted")],
            ctx(1, "credential_harvest"))],
        seniority_level="Staff", as_of=NOW,
    )
    clicked_t3 = score_employee(
        [score_campaign([Event("opened"), Event("clicked")],
                        ctx(3, "credential_harvest"))],
        seniority_level="Staff", as_of=NOW,
    )
    assert submitted_t1.hrs > clicked_t3.hrs

    # ...but on SUSCEPTIBILITY, the easy-lure victim is (at least) as high
    assert submitted_t1.susceptibility_index > clicked_t3.susceptibility_index


# --- Layer 3: decay + normalisation --------------------------------------
def test_recent_failure_weighs_more_than_old():
    old = score_campaign([Event("clicked"), Event("submitted")],
                         ctx(1, "credential_harvest", days_ago=360))
    recent_clean = score_campaign([Event("reported")],
                                  ctx(1, "credential_harvest", days_ago=1))
    emp = score_employee([old, recent_clean], "Staff", as_of=NOW)
    # improved recently -> HRS should be well below the old failure's raw risk
    assert emp.hrs < old.campaign_risk_severity


def test_hrs_bounds_and_band():
    # worst case, every campaign a full Tier-3 credential submit, recent
    worst = [
        score_campaign(
            [Event("opened"), Event("clicked"), Event("dwell", value=30),
             Event("field_focus"), Event("typed_no_submit"),
             Event("submitted"), Event("download"),
             Event("chatbot_turn"), Event("chatbot_turn"),
             Event("chatbot_turn"), Event("chatbot_turn"),
             Event("chatbot_disclosure")],
            ctx(3, "mixed", days_ago=0, cid=f"c{i}"))
        for i in range(3)
    ]
    emp = score_employee(worst, "Exec", as_of=NOW)
    assert 0 <= emp.hrs <= 100
    assert emp.hrs_band in {"High", "Critical"}
    # org risk applies the exec multiplier on top
    assert emp.org_risk >= emp.hrs


def test_org_risk_separates_role():
    cs = [score_campaign([Event("clicked"), Event("submitted")],
                         ctx(2, "credential_harvest"))]
    staff = score_employee(cs, "Staff", as_of=NOW)
    exec_ = score_employee(cs, "Exec", as_of=NOW)
    # identical behaviour => identical HRS, but different org priority
    assert staff.hrs == exec_.hrs
    assert exec_.org_risk > staff.org_risk


def test_explainability_present():
    cs = score_campaign(
        [Event("clicked"), Event("submitted", breached=True)],
        ctx(1, "credential_harvest"))
    emp = score_employee([cs], "Staff", as_of=NOW)
    assert cs.reasons and emp.summary
    assert any("submitted" in r for r in cs.reasons)
