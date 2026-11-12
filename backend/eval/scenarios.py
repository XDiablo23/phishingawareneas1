"""
Score-sanity evaluation.

A scripted battery of scenarios with a known expected outcome, asserting
the engine behaves sensibly and consistently with the chosen SEVERITY
weighting. This is the automatable half of the spec's evaluation plan;
it doubles as a regression guard whenever constants are re-tuned.

Run:  python -m eval.scenarios      (or via scripts/run_eval.py)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.scoring import Event, CampaignContext, score_campaign, score_employee
from app.scoring import constants as C

NOW = datetime(2027, 1, 15, tzinfo=timezone.utc)


def _ctx(tier, vector, days_ago=0, cid="c"):
    return CampaignContext(campaign_id=cid, tier=tier, vector=vector,
                           campaign_date=NOW - timedelta(days=days_ago))


def _emp(campaign_scores, seniority="Staff"):
    return score_employee(campaign_scores, seniority_level=seniority, as_of=NOW)


@dataclass
class Scenario:
    name: str
    check: Callable[[], tuple[bool, str]]


def _s_depth_monotonic():
    shallow = _emp([score_campaign([Event("opened"), Event("clicked")],
                                   _ctx(2, "credential_harvest"))])
    deep = _emp([score_campaign(
        [Event("opened"), Event("clicked"), Event("dwell", value=20),
         Event("field_focus"), Event("submitted")],
        _ctx(2, "credential_harvest"))])
    ok = deep.hrs > shallow.hrs
    return ok, f"deep HRS {deep.hrs} > shallow HRS {shallow.hrs}"


def _s_tier_severity_ordering():
    ev = [Event("clicked"), Event("submitted")]
    h1 = _emp([score_campaign(ev, _ctx(1, "credential_harvest"))]).hrs
    h2 = _emp([score_campaign(ev, _ctx(2, "credential_harvest"))]).hrs
    h3 = _emp([score_campaign(ev, _ctx(3, "credential_harvest"))]).hrs
    ok = h1 < h2 < h3
    return ok, f"HRS by tier 1/2/3 = {h1}/{h2}/{h3} (increasing)"


def _s_susceptibility_inverts():
    ev = [Event("clicked"), Event("submitted")]
    s1 = _emp([score_campaign(ev, _ctx(1, "credential_harvest"))]).susceptibility_index
    s3 = _emp([score_campaign(ev, _ctx(3, "credential_harvest"))]).susceptibility_index
    ok = s1 > s3
    return ok, f"susceptibility T1 {s1} > T3 {s3} (easy lure => more susceptible)"


def _s_submitted_low_beats_clicked_high():
    sub_t1 = _emp([score_campaign(
        [Event("opened"), Event("clicked"), Event("dwell", value=20),
         Event("field_focus"), Event("submitted")],
        _ctx(1, "credential_harvest"))])
    click_t3 = _emp([score_campaign([Event("opened"), Event("clicked")],
                                    _ctx(3, "credential_harvest"))])
    ok = sub_t1.hrs > click_t3.hrs
    return ok, f"submit-T1 HRS {sub_t1.hrs} > click-only-T3 HRS {click_t3.hrs}"


def _s_reporting_protective():
    reporter = _emp([score_campaign([Event("reported")],
                                    _ctx(3, "credential_harvest"))])
    clicker = _emp([score_campaign([Event("clicked")],
                                   _ctx(1, "credential_harvest"))])
    ok = reporter.hrs <= clicker.hrs and reporter.hrs == 0
    return ok, f"reporter HRS {reporter.hrs} <= clicker HRS {clicker.hrs}"


def _s_recency_decay():
    # Decay reweights campaigns RELATIVE to each other (the sum(r-w)/sum(w)
    # ratio cancels the weight for a lone campaign). So we give each persona
    # the SAME two events - one severe failure, one click-only - and vary
    # only WHICH is recent. The persona whose severe failure is recent must
    # score higher.
    severe = [Event("clicked"), Event("dwell", value=20),
              Event("field_focus"), Event("submitted")]
    mild = [Event("opened"), Event("clicked")]

    recent_fail = _emp([
        score_campaign(severe, _ctx(1, "credential_harvest", days_ago=2, cid="a")),
        score_campaign(mild, _ctx(1, "credential_harvest", days_ago=300, cid="b")),
    ])
    old_fail = _emp([
        score_campaign(severe, _ctx(1, "credential_harvest", days_ago=300, cid="a")),
        score_campaign(mild, _ctx(1, "credential_harvest", days_ago=2, cid="b")),
    ])
    ok = recent_fail.hrs > old_fail.hrs
    return ok, (f"recent-failure HRS {recent_fail.hrs} > old-failure HRS "
                f"{old_fail.hrs} (same events, decay reweights by recency)")


def _s_penetration_fairness():
    link = score_campaign([Event("opened"), Event("clicked")],
                          _ctx(1, "link_only"))
    cred = score_campaign([Event("opened"), Event("clicked")],
                          _ctx(1, "credential_harvest"))
    ok = link.penetration_ratio == 1.0 and cred.penetration_ratio < 0.5
    return ok, (f"click-only penetration: link_only {link.penetration_ratio} "
                f"vs credential {cred.penetration_ratio}")


def _s_org_overlay_separation():
    cs = [score_campaign([Event("clicked"), Event("submitted")],
                         _ctx(2, "credential_harvest"))]
    staff = _emp(cs, "Staff")
    execu = _emp(cs, "Exec")
    ok = staff.hrs == execu.hrs and execu.org_risk > staff.org_risk
    return ok, (f"equal HRS {staff.hrs}; org_risk exec {execu.org_risk} "
                f"> staff {staff.org_risk}")


def _s_band_boundaries():
    checks = []
    for val, expected in [(0, "Low"), (24, "Low"), (25, "Moderate"),
                          (49, "Moderate"), (50, "High"), (74, "High"),
                          (75, "Critical"), (100, "Critical")]:
        label = next(l for lo, hi, l in C.BANDS if lo <= val <= hi)
        checks.append(label == expected)
    ok = all(checks)
    return ok, f"{sum(checks)}/{len(checks)} band-boundary points correct"


SCENARIOS = [
    Scenario("depth monotonicity", _s_depth_monotonic),
    Scenario("tier severity ordering", _s_tier_severity_ordering),
    Scenario("susceptibility inversion", _s_susceptibility_inverts),
    Scenario("submitted-T1 outranks clicked-T3 (HRS)", _s_submitted_low_beats_clicked_high),
    Scenario("reporting is protective", _s_reporting_protective),
    Scenario("recency decay", _s_recency_decay),
    Scenario("penetration cross-vector fairness", _s_penetration_fairness),
    Scenario("org overlay separates role", _s_org_overlay_separation),
    Scenario("band boundaries", _s_band_boundaries),
]


def run_scenarios():
    results = []
    for sc in SCENARIOS:
        try:
            ok, detail = sc.check()
        except Exception as e:  # a broken scenario is a failure, not a crash
            ok, detail = False, f"raised {type(e).__name__}: {e}"
        results.append((sc.name, ok, detail))
    return results


def main():
    results = run_scenarios()
    print("\nScore-sanity evaluation")
    print("=" * 66)
    passed = 0
    for name, ok, detail in results:
        flag = "PASS" if ok else "FAIL"
        passed += ok
        print(f"  [{flag}] {name}")
        print(f"         {detail}")
    print("-" * 66)
    print(f"  {passed}/{len(results)} scenarios passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
