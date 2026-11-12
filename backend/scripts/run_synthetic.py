"""
End-to-end demo with no external parts.

    python scripts/run_synthetic.py [n_employees] [n_campaigns]

Generates a synthetic organization, runs the full scoring pipeline, and
prints the HRS/susceptibility distribution plus one worked example so you
can see the engine and explainability output without a database or UI.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.synthetic import generate_dataset
from app.scoring.service import score_synthetic
from app.scoring import constants as C


def bar(n: int, width: int = 1) -> str:
    return "#" * (n * width)


def main():
    n_emp = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    n_camp = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    now = datetime.now(timezone.utc)

    ds = generate_dataset(n_employees=n_emp, n_campaigns=n_camp, now=now)
    emp_scores, camp_scores = score_synthetic(ds, as_of=now)

    print(f"\nTenant: {ds.tenant_name}")
    print(f"Employees: {len(ds.employees)}   Campaigns: {len(ds.campaigns)}"
          f"   Events: {len(ds.events)}   Campaign-scores: {len(camp_scores)}")

    print("\nCampaigns:")
    for c in sorted(ds.campaigns, key=lambda x: x.campaign_date):
        age = (now - c.campaign_date).days
        print(f"  {c.campaign_id}  T{c.tier}  {c.vector:<20} "
              f"{len(c.target_ids):>3} targets  {age:>3}d ago")

    # --- HRS band distribution
    bands = Counter(s.hrs_band for s in emp_scores.values())
    print("\nHRS band distribution:")
    for _, _, label in C.BANDS:
        print(f"  {label:<9} {bands.get(label,0):>3}  {bar(bands.get(label,0))}")

    hrs_vals = [s.hrs for s in emp_scores.values()]
    sus_vals = [s.susceptibility_index for s in emp_scores.values()]
    print(f"\nHRS            min {min(hrs_vals):5.1f}  "
          f"mean {sum(hrs_vals)/len(hrs_vals):5.1f}  max {max(hrs_vals):5.1f}")
    print(f"Susceptibility min {min(sus_vals):5.1f}  "
          f"mean {sum(sus_vals)/len(sus_vals):5.1f}  max {max(sus_vals):5.1f}")

    # --- top risks
    ranked = sorted(emp_scores.items(),
                    key=lambda kv: kv[1].org_risk, reverse=True)
    id_to_emp = {e.employee_id: e for e in ds.employees}
    print("\nTop 8 by org-risk (priority):")
    print(f"  {'name':<22}{'dept':<12}{'level':<10}"
          f"{'HRS':>6}{'band':>10}{'susc':>7}{'orgR':>8}")
    for eid, s in ranked[:8]:
        e = id_to_emp[eid]
        print(f"  {e.full_name:<22}{e.department:<12}{e.seniority_level:<10}"
              f"{s.hrs:>6.1f}{s.hrs_band:>10}{s.susceptibility_index:>7.1f}"
              f"{s.org_risk:>8.1f}")

    # --- one worked example (explainability)
    worked_id, worked = ranked[0]
    e = id_to_emp[worked_id]
    print(f"\nWorked example - {e.full_name} ({e.job_title}):")
    print(f"  {worked.summary}")
    for cs in sorted(worked.campaign_scores,
                     key=lambda c: c.campaign_risk_severity, reverse=True)[:4]:
        print(f"   - Tier-{cs.tier} {cs.vector}: depth {cs.compromise_depth:.0f}, "
              f"risk {cs.campaign_risk_severity:.0f}, "
              f"penetration {cs.penetration_ratio:.0%}")
        print(f"       {', '.join(cs.reasons)}")

    print("\nOK - full pipeline ran (schema -> synthetic events -> scoring).\n")


if __name__ == "__main__":
    main()
