"""Tests for the evaluation harness."""

from eval.scenarios import run_scenarios
from eval.tracking_accuracy import tracking_accuracy
from eval.email_realism import aggregate_realism_csv


def test_all_score_sanity_scenarios_pass():
    results = run_scenarios()
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed, f"failing scenarios: {failed}"
    assert len(results) >= 9


def test_tracking_accuracy_math():
    gt = [
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "clicked"},
        {"employee_id": "e2", "campaign_id": "c1", "event_type": "clicked"},
    ]
    cap = [
        {"employee_id": "e1", "campaign_id": "c1", "event_type": "clicked"},  # tp
        {"employee_id": "e3", "campaign_id": "c1", "event_type": "clicked"},  # fp
        # e2 missing -> fn
    ]
    rep = tracking_accuracy(gt, cap)
    o = rep["overall"]
    assert o["tp"] == 1 and o["fp"] == 1 and o["fn"] == 1
    assert o["precision"] == 0.5 and o["recall"] == 0.5


def test_perfect_tracking_is_1():
    gt = [{"employee_id": "e1", "campaign_id": "c1", "event_type": "opened"}]
    rep = tracking_accuracy(gt, gt)
    assert rep["overall"]["precision"] == 1.0
    assert rep["overall"]["recall"] == 1.0
    assert rep["overall"]["f1"] == 1.0


def test_email_realism_aggregation():
    csv_text = (
        "rater_id,email_id,is_simulation,guessed_simulation,realism\n"
        "r1,e1,1,0,4\n"   # sim, not detected
        "r2,e1,1,1,4\n"   # sim, detected
        "r1,e2,0,0,5\n"   # real, correctly not flagged
        "r2,e2,0,1,5\n"   # real, false alarm
    )
    rep = aggregate_realism_csv(csv_text)
    assert rep["n_ratings"] == 4 and rep["n_emails"] == 2
    assert rep["detection_rate"] == 0.5      # 1 of 2 sim ratings detected
    assert rep["false_alarm_rate"] == 0.5    # 1 of 2 real ratings flagged
    assert rep["mean_realism_simulations"] == 4.0
    assert rep["mean_realism_real"] == 5.0
