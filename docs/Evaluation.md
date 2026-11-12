# Evaluation Plan & Results

AI-Powered Phishing Awareness & Risk-Scoring Platform - Capstone 2.

This document defines how the platform is evaluated, the metrics used, how
to reproduce every result, and the current findings. It is written to drop
into the capstone report. It covers the **measurement layer** built here;
the simulation engine (GoPhish) is evaluated only through the events it
feeds in.

## 1. Evaluation questions

The build has three claims that need evidence, each mapped to an evaluation:

| # | Claim | Evaluation | Type |
|---|-------|------------|------|
| E1 | The risk score is **valid** - it orders people the way a security team would expect, and behaves sensibly as behaviour and difficulty vary. | Score-sanity scenarios | Automated |
| E2 | The **tracking** the score depends on is accurate - recorded events match what recipients actually did. | Tracking-accuracy study | Semi-automated (needs QA runs) |
| E3 | The simulated lures are **realistic** enough to elicit representative behaviour. | Blind rater panel | Human study |

A fourth, supporting line of evidence is ordinary **software correctness**:
119 automated tests over the schema, scoring engine, API, access control,
the GoPhish/directory adapters, secret encryption, session/CSRF handling,
and the remediation portal.

## 2. E1 - Scoring validity (score-sanity)

### Method
Because there is no labelled ground-truth "true risk" for a person, we
evaluate the score the way numerical models without gold labels are
evaluated: **property-based / metamorphic testing**. We assert relationships
that must hold for any defensible risk model, using scripted scenarios with
a known expected ordering, and check the engine honours them. This also
guards against regressions whenever the scoring constants are re-tuned.

### Scenarios and what each proves
1. **Depth monotonicity** - going further in a campaign never lowers risk.
2. **Tier severity ordering** - at equal depth, a harder lure (Tier 3)
   scores higher than an easier one (severity view).
3. **Susceptibility inversion** - the secondary index inverts this: being
   fooled by an *easy* lure signals higher susceptibility.
4. **Submitted-T1 outranks Clicked-T3** - depth dominates tier, so
   submitting credentials to an easy lure is worse than merely clicking a
   hard one. (The headline decision the model encodes.)
5. **Reporting is protective** - reporting before clicking yields zero
   compromise and sits below any real engagement.
6. **Recency decay** - with identical events, the person whose *severe*
   failure is recent scores higher than one whose severe failure is old.
7. **Penetration fairness** - a click on a link-only lure is 100% of that
   vector's reachable depth, while the same click on a credential lure is
   far short of its ceiling.
8. **Org-overlay separation** - role changes org-priority but not the
   individual HRS (identical behaviour ⇒ identical HRS).
9. **Band boundaries** - scores map to the correct Low/Moderate/High/
   Critical bands at the boundary values.

### Metric
Pass/fail per scenario; the suite is a hard gate (any failure fails the
process).

### Result
**9 / 9 scenarios pass.** Illustrative values from a run:

- Tier severity: HRS 28.1 / 36.6 / 45.0 for Tiers 1 / 2 / 3 at equal depth.
- Susceptibility inversion: 45.0 (T1) vs 32.1 (T3) on identical events.
- Submitted-T1 (35.6) > Clicked-T3 (17.0).
- Recency: recent-failure 32.2 vs old-failure 12.8 on identical events.

### Reproduce
```bash
cd backend && python scripts/run_eval.py      # section 1
# or as part of the test suite:
python -m pytest app/tests/test_eval.py app/tests/test_scoring.py -q
```

### Threats to validity
Property tests confirm the model is *self-consistent and sensible*, not that
its absolute numbers match real-world compromise probability. Calibration
against real outcomes (below) is future work. Two modelling choices worth
noting in the report, both consequences of HRS being a decay-weighted
average: the distribution skews Low (a single severe failure is diluted by
ignored campaigns), and a lone campaign does not decay over time. Both are
faithful to the agreed formula and are tunable in `constants.py`.

## 3. E2 - Tracking accuracy

### Method
The score is only as trustworthy as its inputs, so the tracker is validated
independently. Run a **scripted QA campaign** against a small set of team
mailboxes where a tester performs a *known* sequence of actions (open only;
open + click; open + click + submit; report; etc.). This scripted log is
the **ground truth**. Compare it to what the tracker captured and this
platform ingested.

An event is identified by `(employee, campaign, stage)`; repeated events of
the same stage collapse to one, so we measure **stage detection**, not raw
counts.

### Metrics
Precision, recall, and F1 - overall and per event type - where a false
negative is a real action the tracker missed and a false positive is an
event it reported that didn't happen (e.g. a prefetch/scanner open).

### Reproduce
Place the two logs (lists of `{employee_id, campaign_id, event_type}`) into
`eval/tracking_accuracy.py` (replace `_demo()`), then:
```bash
cd backend && python -m eval.tracking_accuracy
```

### Status
Harness verified on synthetic logs (demo: overall P/R/F1 ~ 0.86 with one
injected miss and one spurious open; `clicked` recall 0.50 from the missed
click). **Field numbers to be collected during the Oct 2026-Feb 2027 QA
runs** and pasted into the results table below.

### Threats to validity
Open-tracking is inherently noisy (image proxies and security scanners
inflate opens; blocked images suppress them), so `opened` precision/recall
will be the weakest and should be reported with that caveat. Click/submit
are far more reliable and matter more to the score.

## 4. E3 - Email realism

### Method
A **blind rater panel**: assemble a set mixing genuine corporate emails and
simulated lures across tiers. Raters, blind to which is which, (a) rate each
for believability on a 1-5 scale and (b) guess whether it is a simulation.

### Metrics
- **Mean realism** (1-5), overall and for simulations vs real emails.
- **Detection rate** - how often raters correctly flag a simulation
  (lower ⇒ more convincing).
- **False-alarm rate** - how often raters flag a *real* email as simulated
  (contextualises detection: if raters call everything a sim, a low
  detection rate is meaningless).

### Reproduce
Collect ratings with `eval/templates/realism_ratings_template.csv`
(`rater_id, email_id, is_simulation, guessed_simulation, realism`), then
aggregate:
```bash
cd backend && python -m eval.email_realism         # runs on the template
# in code: aggregate_realism_csv(open('your_ratings.csv').read())
```

### Status
Aggregation logic verified on template data. **Panel to be run** with the
team's lure set; results pasted below.

### Threats to validity
Rater pool size and composition (familiarity with the impersonated brands)
strongly affect detection; report N and recruitment. Realism is a proxy for
"elicits representative behaviour", not a guarantee of it.

## 5. Software correctness (supporting)

119 automated tests, all passing (93 backend + 26 portal):

- **17** scoring-engine tests (depth, tiers, decay, penetration, org
  overlay, explainability).
- **11** management tests (campaigns/roster/users CRUD, CSV import/export,
  integration configuration).
- **11** directory & GoPhish adapter tests (Entra/LDAP sync, GoPhish group
  and campaign lifecycle, the authorization gate), including a check that a
  "Submitted Data" event carrying a captured password is stored as a
  `submitted` event with **no credential value persisted**.
- **10** security regression tests (response headers, JWT expiry/alg
  enforcement, session cookies, CSRF, CSV formula-injection escaping).
- **9** API/auth tests (seed->login->ingest->recompute->dashboard, RBAC, the
  credential-rejection guardrail on JSON and CSV, departmental-viewer
  scoping).
- **8** webhook/beacon ingestion tests (HMAC verification, credential-drop,
  per-tenant secret, sync idempotency, and the unmapped-event diagnostics:
  an audit row on the HMAC-verified webhook path, deliberately none on the
  public beacon path).
- **7** portal-hook tests (risk floor, in-person mark, dashboard badge).
- **6** production-hardening tests, **6** secret-encryption tests, **4**
  evaluation-harness tests, **4** beacon-trends tests (backend).
- **26** portal-side tests (the escalation flow against a fake
  PhishAwareness, encryption including the legacy-credential scrub on
  upgrade, and the service-token client).

```bash
# from the repository root, with the backend virtualenv active
cd backend && python -m pytest app/tests -q
cd ../portal && python -m pytest app/tests -q   # the portal reuses that venv
```

On Windows without the virtualenv activated, call its interpreter directly:

```bat
backend\.venv\Scripts\python.exe -m pytest backend\app\tests -q
backend\.venv\Scripts\python.exe -m pytest portal\app\tests -q
```

## 6. Results summary

| Evaluation | Metric | Target | Result |
|-----------|--------|--------|--------|
| E1 Scoring validity | scenarios passing | 9 / 9 | **9 / 9** |
| Software correctness | tests passing | all | **119 / 119** |
| E2 Tracking accuracy | click/submit F1 | >= 0.95 | _QA run pending_ |
| E2 Tracking accuracy | open F1 | report w/ caveat | _QA run pending_ |
| E3 Realism | mean realism (sims) | >= 3.5 / 5 | _panel pending_ |
| E3 Realism | detection rate | <= 0.5 | _panel pending_ |

## 7. Reproducing everything at once

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest app/tests -q      # correctness + E1
python scripts/run_eval.py         # E1 + E2/E3 harness demonstrations
python scripts/run_synthetic.py    # end-to-end pipeline on synthetic data
```

## 8. Limitations

- E1 establishes internal validity (self-consistency), not calibration to
  real compromise rates; calibration needs longitudinal outcome data.
- E2 and E3 require live runs and a rater panel; the harness and templates
  are complete and tested, and the numbers are to be filled from the
  scheduled runs.
- The synthetic distribution is illustrative and inherits the two modelling
  choices noted in §2; it is not evidence about a real population.
