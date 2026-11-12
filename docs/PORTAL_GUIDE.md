# Awareness & Remediation Portal - Technical Guide

*PhishAwareness - AI-Powered Phishing Awareness & Risk-Scoring Platform*
*Companion service to the measurement platform. This document describes the
portal's architecture, its automatic remediation/escalation policy, and the
REST contract it uses to talk to PhishAwareness.*

---

## 1. Purpose and placement

The PhishAwareness platform **measures** human phishing risk: it scores
simulation event-metadata into a per-employee Human Risk Score (HRS) with four
bands (Low, Moderate, High, Critical). Measuring risk is only half of an
awareness programme - the other half is **doing something about it**. The
Awareness & Remediation Portal is that other half:

* it **trains** employees (non-skippable lessons + exams, interactive learning);
* it lets admins **publish policies** employees must read and agree to;
* it turns a risk score into **consequences** automatically - remediation for
  High risk, and, for people who stay elevated too long, a mark for **in-person**
  security awareness plus an outbound **ticket** to the org's ticketing system.

It is a **separate service** with its **own database**. The only coupling to
PhishAwareness is a small, well-defined REST contract (Section 7). This keeps the
measurement platform's §2 boundary intact - the portal is a defensive training
tool and never touches lure generation, delivery, or credential capture.

```
 Employee browser ─┐
                   ├─►  Portal  (FastAPI :8100, SQLite)  ──REST──►  PhishAwareness API (:8000)
 Admin browser  ───┘         │                                       risk scores + 3 signals
                             └────── webhook (JSON) ──────►  Org ticketing (e.g. Jira)
```

---

## 2. Architecture

| Layer | Choice | Notes |
|---|---|---|
| Runtime | FastAPI + Uvicorn, port **8100** | Separate process from PhishAwareness |
| Storage | SQLAlchemy 2.0 + SQLite (`portal.db`) | Its **own** DB; no shared tables |
| Employee auth | Native accounts, PBKDF2 (200k rounds) + JWT | Employees register in the portal |
| Admin auth | **Delegated** to PhishAwareness `/auth/login` | Admins reuse their PA operator login |
| PA client | `httpx`, per-tenant service token (header) | Section 7 |
| Front end | Single-page app (vanilla JS), served by the portal | Employee + admin in one app, no build step |
| Automation | Optional background sync loop (`PORTAL_AUTO_SYNC_SECONDS`) | Launcher sets 300s |

The portal deliberately reuses the backend's Python 3.12 virtual environment, so
there is nothing extra to install and the whole stack still starts from one
`Start-PhishAwareness.bat`.

---

## 3. Employee lifecycle (state machine)

A `PortalUser` moves through four states:

```
  register
     │  (map to PhishAwareness, assign mandatory onboarding)
     ▼
 ONBOARDING ──(all onboarding modules passed)──► ACTIVE
                                                   │  push Moderate floor to PA
     ┌─────────────────────────────────────────────┤
     ▼                                              ▼
 REMEDIATION  ◄──(High/Critical, or new policy)── (sync)
     │  (remediation modules cleared)
     ▼
 ACTIVE  ──(stuck High/Critical past tolerance)──► FLAGGED
                                                     │  set in-person mark in PA
                                                     └► raise ticket to ticketing system
```

* **ONBOARDING** - the account exists but access is provisional; the person must
  finish the mandatory awareness module(s) first.
* **ACTIVE** - onboarding done; a Moderate baseline floor is held in
  PhishAwareness until real behaviour supersedes it.
* **REMEDIATION** - has outstanding remediation (from a failure or a new policy).
* **FLAGGED** - has been elevated too long; in-person awareness is required and a
  ticket has been raised. Clears automatically if the person recovers below High.


---

## 4. The remediation / escalation policy

The engine (`portal/app/remediation.py`) is idempotent and safe to run
repeatedly; the background loop and the admin "Run sync" button both call it.

| Trigger | Condition | Automatic action |
|---|---|---|
| **Sign-up** | New account created | Ensure a PhishAwareness employee exists; assign onboarding module(s); status -> ONBOARDING |
| **Onboarding complete** | All onboarding assignments passed | Push **Moderate floor** (default HRS 35) to PhishAwareness; status -> ACTIVE |
| **Phishing failure** | On sync, band is High/Critical AND (a new campaign was scored OR the band worsened) | Assign the next remediation module on the ladder; status -> REMEDIATION |
| **New/updated policy** | Admin publishes a policy with *trigger remediation* on | Assign a remediation module to everyone; require acknowledgement; status -> REMEDIATION |
| **Stuck elevated** | Band stays High/Critical >= `inperson_after_days` | Set **needs-in-person-awareness** in PhishAwareness; raise a **ticket**; status -> FLAGGED |
| **Recovery** | Band drops to Low/Moderate | Clear the in-person mark; status -> ACTIVE |

**The remediation ladder.** Remediation modules carry a `level`. A first failure
assigns level 1 (e.g. *Spotting Phishing Emails*); a repeat failure, once level 1
is completed, assigns level 2 (*Advanced & Targeted Phishing - Extended*). If a
persistent re-offender exhausts the ladder, the deepest module is re-assigned.
This is the "same videos -> new videos -> extended videos -> ..." progression.

**Why a floor, not a score.** The portal never *writes a score*; it writes a
**floor** - a value the HRS is held at-or-above. A new hire with no simulation
history would otherwise read Low (0). The Moderate floor says "unproven, treat as
Moderate" until real behaviour produces a higher score, at which point the real
score wins. The floor only ever raises, never lowers, an HRS.

---

## 5. Training content (non-skippable lessons + exams)

A **Module** is an on-page lesson (authored HTML) with an optional embedded video
and an optional link to an external open-source resource, followed by an exam.

* **Non-skippable** is enforced on the **server**: the client sends periodic
  "watch" heartbeats; the server accumulates `watched_seconds` (capped per beat)
  and refuses to accept an exam until `watched_seconds >= min_seconds`. This can't
  be bypassed from the UI alone.
* **Exams** are multiple-choice with a configurable pass threshold (default 70%).
  A module is only **completed** when the dwell is satisfied *and* the exam is
  passed; every attempt is recorded, wrong answers are shown with explanations.

**Seeded open-source content.** The library ships with authored lessons that link
to real, free resources, so an org can start immediately and swap in its own:

| Module | Kind | Free resource referenced |
|---|---|---|
| Security Awareness Essentials | onboarding | CISA Cybersecurity Awareness & Training |
| Spotting Phishing Emails | remediation L1 | NCSC phishing guidance |
| Advanced & Targeted Phishing (Extended) | remediation L2 | SANS **OUCH!** newsletter |
| Acceptable Use & Data Handling Refresher | policy | Open-source SCORM catalogue (RansomLeak) |

Admins can create modules (including a YouTube-style embed URL and their own
exam questions) from the **Modules** screen, so SCORM/xAPI or hosted-video
content can be plugged in without code changes.

---

## 6. Policies and acknowledgements

Admins publish a policy as text or by **uploading a document** (PDF/DOCX/...).
Each active policy that requires acknowledgement becomes an outstanding
obligation for every employee until they explicitly agree. Publishing a policy
can also **trigger remediation** (assign a chosen module to everyone), which is
the "org uploads a new document -> everyone re-trains" flow.


---

## 7. PhishAwareness integration contract

The portal authenticates to PhishAwareness with a **per-tenant service
token** (header `X-Portal-Token`) and calls a dedicated, additive API
surface added to PhishAwareness for this purpose
(`backend/app/api/routes_portal.py`), all under
`/api/v1/tenants/{tenant_id}/portal`. Generate/rotate the token from
PhishAwareness's Manage -> Integration screen (`portal_service_token`);
the token is scoped to exactly this router - unlike an operator/admin JWT,
a leaked token can't reach campaign launch, roster, or user management.

| Method + path | Used for |
|---|---|
| `GET  /portal/employees` | Pull every employee's current HRS/band + portal marks |
| `GET  /portal/employees/by-email?email=` | Resolve one employee (the join key) |
| `POST /portal/employees/ensure` | Find-or-create an employee by email on first sign-up |
| `POST /portal/employees/{id}/risk-floor` | Set/clear the **baseline floor** (`{value}`) |
| `POST /portal/employees/{id}/inperson-flag` | Raise/clear the **in-person mark** (`{on, reason}`) |

On the PhishAwareness side these three writes are additive `Employee` columns
(`risk_floor`, `needs_inperson_awareness`, `inperson_reason`, `inperson_since`),
a scoring hook that applies the floor during `score_tenant_from_db`, and the
`needs_inperson_awareness` badge surfaced on the dashboard. A migration
(`c3d4e5f6a7b8`) adds the columns; nothing else in the platform changed.

The portal client (`portal/app/pa_client.py`) sends the configured service
token on every call - no login step, no cached/refreshed session token for
this automation path. If PhishAwareness is unreachable, portal features still
work (sign-up, training) and mapping/pushes are retried on the next sync - the
services are loosely coupled by design.

---

## 8. Ticketing integration (outbound)

When someone is flagged for in-person awareness, the portal POSTs a neutral JSON
envelope to a webhook the org configures (Ticketing screen). The portal **only
sends information**; the org maps it into a Jira issue (or anything else) via
their own automation. Every attempt is logged (payload, status, response).

```json
{
  "event": "inperson_awareness_required",
  "source": "PhishAwareness Awareness & Remediation Portal",
  "generated_at": "2026-08-23T21:12:04Z",
  "severity": "high",
  "summary": "In-person security awareness required: New Hire",
  "employee": {"name":"New Hire","email":"newhire@demo.co","department":"Finance","job_title":"Analyst"},
  "risk": {"hrs":85.0,"band":"Critical","elevated_since":"2026-07-20T...","days_elevated":34},
  "reason": "Stuck Critical for 34 days despite automated remediation (HRS 85.0).",
  "recommended_action": "Schedule a mandatory in-person security awareness session; ...",
  "phishawareness_employee_id": "..."
}
```

Config supports an optional auth header (e.g. `Authorization: Bearer ...`) so it
works with authenticated inbound webhooks. A **Send test ticket** button posts a
sample payload so integrators can wire and verify the endpoint before any real
escalation fires.

---

## 9. Security and the measurement boundary

* **Defensive only.** The portal is training + remediation. It stores no lure
  content and no simulation credentials, and it cannot generate, send, or clone
  anything. It upholds the same §2 boundary as the measurement platform.
* **Least-signal coupling.** The portal<->PhishAwareness link carries exactly three
  writes (floor, in-person mark, ensure) and reads only scores - all metadata.
* **Auth separation.** Employees are the portal's own accounts (hashed with
  PBKDF2, never reversible); admins are verified against PhishAwareness on
  login, and nothing from that login is persisted. Background automation
  authenticates separately with a narrowly-scoped, encrypted-at-rest service
  token (generated on the PhishAwareness side and pasted into Settings) -
  the portal never becomes a second place where an admin's real password
  lives, even transiently.
* **Server-side enforcement.** Dwell and exam gating are enforced server-side, so
  completion can't be forged by clicking around the UI.


---

## 10. Data model (portal database)

| Table | Purpose |
|---|---|
| `portal_users` | Employee accounts + cached PA snapshot (`pa_employee_id`, `last_hrs`, `last_band`, `elevated_since`, `inperson_escalated`, `status`) |
| `modules` / `questions` | Training modules (lesson, dwell, thresholds) and their exam questions |
| `assignments` | A module assigned to a user, with server-tracked `watched_seconds`, attempts, best score |
| `exam_attempts` | Every exam submission (score, pass/fail, answers) |
| `policies` / `policy_acks` | Published policies and per-user acknowledgements |
| `ticket_config` / `ticket_log` | Outbound webhook config (singleton) and a log of every ticket attempt |
| `settings` | Singleton: PA connection + escalation parameters (overrides `.env` defaults) |

---

## 11. Running and a demo walkthrough

1. `Start-PhishAwareness.bat` (root) starts the API, web console, portal, and
   GoPhish, and opens the console and the portal.
2. In the **console** (`:5173`): create the demo org and sign in.
3. In the **portal** (`:8100`) -> **Administrator**: sign in with the same
   operator email/password. This wires which PhishAwareness backend/tenant
   the portal points at. In PhishAwareness -> Manage -> Integration,
   generate a **Portal service token** and paste it into the portal's
   Settings screen - this is what background automation actually
   authenticates with (not the login above).
4. Portal -> **Employee** -> *Create account*: you are placed in onboarding.
   Complete the lesson (the exam unlocks after the dwell) and pass it - the
   portal pushes a Moderate baseline to PhishAwareness (visible on the console).
5. Back as admin, configure the **Ticketing** webhook (a test sink is provided:
   `portal/tools/webhook_sink.py`) and click **Run sync**. As people's scores
   rise in PhishAwareness, remediation is assigned; if someone is stuck elevated
   past tolerance, an in-person mark appears in PhishAwareness and a ticket fires.

---

## 12. Testing and verification

**Automated tests.**

* PhishAwareness backend: **93/93** pass, including dedicated tests for the
  portal hooks (floor raises but never lowers HRS, band recompute, in-person
  mark surfaced on the dashboard, RBAC).
* Portal: **26/26** pass against a fake PhishAwareness, proving onboarding->floor,
  failure->remediation, policy->remediation+ack, and stuck->in-person+ticket, plus
  the non-skippable dwell gate, admin auth, secret encryption, and the
  service-token client.

**Live end-to-end** (both services running, real HTTP):

| Step | Result |
|---|---|
| Admin delegated login | Tenant id correctly derived from PhishAwareness |
| Employee sign-up | Employee created in PhishAwareness via `ensure` |
| Onboarding completed | Floor **35 / Moderate** pushed to PhishAwareness |
| Risk raised to Critical -> sync | Remediation assigned; **in-person mark set in PhishAwareness** |
| Stuck-elevated escalation | Ticket POSTed to the webhook - **HTTP 200**, well-formed payload |

---

## 13. Limitations and future work

* **Single org per portal instance.** The portal connects to one PhishAwareness
  tenant. Multi-tenant portal hosting is a straightforward extension (scope the
  singletons per tenant).
* **Dwell is time-based**, not attention-based. For stricter proof-of-viewing,
  plug in a real SCORM/xAPI player (the module already carries an embed URL) and
  record completion from the Learning Record Store.
* **Ticketing is fire-and-forget.** The portal logs the send and the response but
  does not track the downstream ticket's lifecycle - by design ("we only send
  info; the org integrates it as they wish").
* **Service credential storage.** ~~The automation credential is stored like
  any integration secret~~ - resolved: automation now authenticates with a
  narrowly-scoped, rotatable service token instead of a stored operator
  password, encrypted at rest. A hardened deployment would still move the
  key material (`PORTAL_ENCRYPTION_KEY`) to a secret manager rather than an
  env var.
