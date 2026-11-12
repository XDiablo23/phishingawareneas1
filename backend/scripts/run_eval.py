"""
Run the full evaluation battery in one shot:

    python scripts/run_eval.py

Score-sanity is a hard pass/fail (exit non-zero on any failure); the
tracking-accuracy and email-realism sections print demonstrations you
replace with real QA-run and rater data.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from eval import scenarios, tracking_accuracy, email_realism


def main():
    rc = scenarios.main()
    tracking_accuracy.main()
    email_realism.main()
    print("=" * 66)
    print("Score-sanity is the automated gate; the other two are scaffolds "
          "for QA-run and rater data.\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
