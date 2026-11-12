"""
Email-realism evaluation (human-in-the-loop aggregation).

Realism can't be unit-tested, so it's measured with a blind rater panel:
raters see a mix of real corporate emails and simulated lures, rate each
for believability (1-5), and guess whether it's a simulation. This module
aggregates the collected ratings into:

  * mean realism per email and overall
  * detection rate  (how often raters correctly flagged a simulation)
  * false-alarm rate (how often raters flagged a *real* email as a sim)

A lower detection rate + higher realism = more convincing simulations. The
false-alarm rate contextualises it (if raters call everything a sim,
detection is meaningless).

Ratings CSV columns:
    rater_id,email_id,is_simulation,guessed_simulation,realism
where `is_simulation` / `guessed_simulation` are 0/1 (or true/false) and
`realism` is 1-5. A template lives at eval/templates/realism_ratings_template.csv.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict


def _b(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "t")


def aggregate_realism(rows: list[dict]) -> dict:
    per_email = defaultdict(lambda: {"realism": [], "is_sim": None})
    det_tp = det_fn = fa_fp = fa_tn = 0

    for r in rows:
        eid = r["email_id"].strip()
        is_sim = _b(r["is_simulation"])
        guess = _b(r["guessed_simulation"])
        try:
            realism = float(r["realism"])
        except (ValueError, KeyError):
            continue
        pe = per_email[eid]
        pe["realism"].append(realism)
        pe["is_sim"] = is_sim

        if is_sim:
            if guess:
                det_tp += 1
            else:
                det_fn += 1
        else:
            if guess:
                fa_fp += 1
            else:
                fa_tn += 1

    email_means = {eid: round(sum(d["realism"]) / len(d["realism"]), 2)
                   for eid, d in per_email.items() if d["realism"]}
    sim_scores = [m for eid, m in email_means.items() if per_email[eid]["is_sim"]]
    real_scores = [m for eid, m in email_means.items() if not per_email[eid]["is_sim"]]

    detection_rate = det_tp / (det_tp + det_fn) if (det_tp + det_fn) else None
    false_alarm_rate = fa_fp / (fa_fp + fa_tn) if (fa_fp + fa_tn) else None

    return {
        "n_ratings": len(rows),
        "n_emails": len(email_means),
        "mean_realism_overall": round(sum(email_means.values()) / len(email_means), 2)
        if email_means else None,
        "mean_realism_simulations": round(sum(sim_scores) / len(sim_scores), 2)
        if sim_scores else None,
        "mean_realism_real": round(sum(real_scores) / len(real_scores), 2)
        if real_scores else None,
        "detection_rate": round(detection_rate, 3) if detection_rate is not None else None,
        "false_alarm_rate": round(false_alarm_rate, 3) if false_alarm_rate is not None else None,
        "per_email_mean_realism": email_means,
    }


def aggregate_realism_csv(csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text))
    return aggregate_realism(list(reader))


TEMPLATE = (
    "rater_id,email_id,is_simulation,guessed_simulation,realism\n"
    "r1,email_01,1,0,4\n"
    "r1,email_02,0,0,5\n"
    "r1,email_03,1,1,2\n"
    "r2,email_01,1,1,3\n"
    "r2,email_02,0,1,4\n"
    "r2,email_03,1,0,4\n"
)


def main():
    report = aggregate_realism_csv(TEMPLATE)
    print("\nEmail-realism evaluation (template data)")
    print("=" * 66)
    for k in ("n_ratings", "n_emails", "mean_realism_overall",
              "mean_realism_simulations", "mean_realism_real",
              "detection_rate", "false_alarm_rate"):
        print(f"  {k:<28} {report[k]}")
    print("-" * 66)
    print("  Collect real ratings with the template CSV, then feed them here.\n")


if __name__ == "__main__":
    main()
