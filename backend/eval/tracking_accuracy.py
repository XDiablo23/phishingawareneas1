"""
Tracking-accuracy evaluation (scaffold).

The scoring layer is only as good as the events it receives, so the
simulation's tracker must be validated separately: when a target actually
does something, does the tracker record it, and does it avoid inventing
events that didn't happen?

This module compares a *ground-truth* event log (what testers actually
did during a scripted run) against the *captured* log (what the tracker
reported and this platform ingested), computing precision / recall / F1
overall and per event type. The team plugs in real logs from scripted
QA runs; a synthetic demonstration is included below.

An event is identified by (employee_id, campaign_id, event_type). Repeated
events of the same type for the same target/campaign collapse to one - we
measure *stage detection*, not raw event counts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


def _keyset(events):
    return {(e["employee_id"], e["campaign_id"], e["event_type"]) for e in events}


@dataclass
class Metric:
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self):
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": round(self.precision, 3),
                "recall": round(self.recall, 3), "f1": round(self.f1, 3)}


def tracking_accuracy(ground_truth: list[dict], captured: list[dict]) -> dict:
    """Return overall and per-event-type precision/recall/F1."""
    gt = _keyset(ground_truth)
    cap = _keyset(captured)

    overall = Metric(tp=len(gt & cap), fp=len(cap - gt), fn=len(gt - cap))

    per_type: dict[str, Metric] = {}
    types = {k[2] for k in gt | cap}
    for t in sorted(types):
        gtt = {k for k in gt if k[2] == t}
        capt = {k for k in cap if k[2] == t}
        per_type[t] = Metric(tp=len(gtt & capt), fp=len(capt - gtt),
                             fn=len(gtt - capt))

    return {
        "overall": overall.as_dict(),
        "by_event_type": {t: mm.as_dict() for t, mm in per_type.items()},
        "ground_truth_events": len(gt),
        "captured_events": len(cap),
    }


# --- demonstration -------------------------------------------------------
def _demo():
    """Synthetic ground-truth vs an imperfect tracker (some misses/extras)."""
    ground_truth = [
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "opened"},
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "clicked"},
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "submitted"},
        {"employee_id": "e2", "campaign_id": "c1", "event_type": "opened"},
        {"employee_id": "e2", "campaign_id": "c1", "event_type": "clicked"},
        {"employee_id": "e3", "campaign_id": "c1", "event_type": "opened"},
        {"employee_id": "e3", "campaign_id": "c1", "event_type": "reported"},
    ]
    captured = [
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "opened"},
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "clicked"},
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "submitted"},
        {"employee_id": "e2", "campaign_id": "c1", "event_type": "opened"},
        # tracker missed e2's click (open-pixel fired, click beacon lost):
        # {"employee_id": "e2", ... "clicked"}  <-- false negative
        {"employee_id": "e3", "campaign_id": "c1", "event_type": "opened"},
        {"employee_id": "e3", "campaign_id": "c1", "event_type": "reported"},
        # tracker double-fired a spurious open (prefetch) -> false positive
        {"employee_id": "e4", "campaign_id": "c1", "event_type": "opened"},
    ]
    return ground_truth, captured


def main():
    gt, cap = _demo()
    report = tracking_accuracy(gt, cap)
    print("\nTracking-accuracy evaluation (demo)")
    print("=" * 66)
    o = report["overall"]
    print(f"  overall   precision {o['precision']:.2f}  recall {o['recall']:.2f}"
          f"  f1 {o['f1']:.2f}   (tp {o['tp']} fp {o['fp']} fn {o['fn']})")
    print("  by event type:")
    for t, mm in report["by_event_type"].items():
        print(f"    {t:<18} P {mm['precision']:.2f}  R {mm['recall']:.2f}  "
              f"F1 {mm['f1']:.2f}  (tp {mm['tp']} fp {mm['fp']} fn {mm['fn']})")
    print("-" * 66)
    print("  Replace _demo() logs with real scripted-run logs to validate "
          "your tracker.\n")


if __name__ == "__main__":
    main()
