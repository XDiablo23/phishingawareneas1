# AI-Powered Phishing Awareness & Risk-Scoring Platform

Capstone 2 - a full-stack platform for running an organisation's phishing-awareness programme end to end.

The platform builds the employee roster from your **directory**, runs authorised
simulations from one console via **GoPhish campaign control**, turns the resulting
interaction events into a per-employee **risk score**, and closes the loop with a
separate **Awareness & Remediation Portal** (training + escalation). It is hardened
by a dedicated secure-coding review and covered by **119 automated tests**.

## Quick start - Windows (one click)

**First time - install everything:** double-click **`setup.bat`**. It installs
Python 3.12, Node.js, and GoPhish (only if missing) via `winget`, then creates the
Python virtual environment and installs all backend, portal, and frontend
dependencies. You get one administrator (UAC) prompt - installing Python/Node
requires it; the app itself runs without admin.

**Every run after that:** double-click **`Start-PhishAwareness.bat`** to launch
everything at once:

- Backend API - http://localhost:8000  (interactive docs at `/docs`)
- Operator console - http://localhost:5173
- Awareness & Remediation Portal - http://localhost:8100
- GoPhish admin (optional) - https://127.0.0.1:3333

The app runs on **SQLite by default - no database to install.** In the console,
click **Create demo organization** (seeds 60 synthetic employees + 8 campaigns and
computes scores), then sign in with one of the demo accounts it prints. That is the
whole loop with no external parts.

## Scope & the safety boundary (read this first)

The platform **measures human risk and trains people - it never manufactures the
attack.** It can orchestrate authorised simulations (build target groups, launch,
schedule, complete, delete campaigns) using **GoPhish** (MIT-licensed) as the
delivery tool, but the deception artefacts - email templates and landing pages -
stay authored **inside GoPhish**. The console selects and uses them; it never
composes, clones, sends, or stores a lure.

Three safety properties are enforced in code, not just policy:

- **No credential ever enters the system.** There is no password/secret column
  anywhere in the schema. On a submission only two booleans are recorded
  (`submitted`, `breached` - the latter from an in-browser HIBP k-anonymity check).
  Ingestion actively **rejects** any event or CSV column that looks like a
  credential (`password`, `otp`, `token`, ...).
- **Tenant isolation + RBAC.** Every domain table carries a `tenant_id`; every
  endpoint is authenticated, role-scoped, and tenant-filtered.
- **Directory sync reads metadata only.** Entra ID and LDAP pull name, email,
  department, title, and office - never anyone's password.

## What's built

| Area | Contents | Status |
|---|---|---|
| Scoring engine | HRS + Susceptibility Index + Org-Risk overlay; depth-, difficulty- and time-aware, fully explainable | Done |
| Ingestion | signed GoPhish webhook, metadata-only landing beacon, read-only sync | Done |
| Directory sync | Microsoft Entra ID (Graph) **and** on-prem Active Directory (LDAP) - metadata only | Done |
| GoPhish control | build groups from the roster, launch / schedule / complete / delete campaigns - authorization gate + audit | Done |
| Operator console | React/Vite - dashboards, people, trends, management, integration | Done |
| Remediation portal | separate FastAPI service - non-skippable training, exams, policies, an escalation engine, and outbound ticketing | Done |
| Security | dedicated hardening pass - headers/CSP, JWT expiry, cross-tenant guard, CSV-formula escaping, upload caps, HTML sanitiser, SSRF checks, fail-closed, rate limiting, encryption at rest for every integration secret, httpOnly-cookie sessions with double-submit CSRF, least-privilege per-tenant service tokens | Done |
| Platform | Alembic migrations, configurable HRS, Docker/Postgres option, CI, LICENSE | Done |

**Tested:** **119 automated tests pass** (93 backend + 26 portal) plus a nine-scenario
score-sanity gate; `pip-audit` and `npm audit` report no known vulnerabilities.
Both frontends build clean.

## Services & ports

| Service | Port | Launch script |
|---|---|---|
| Backend API | 8000 | `run_api.bat` |
| Operator console (React) | 5173 | `run_web.bat` |
| Awareness & Remediation Portal | 8100 | `run_portal.bat` |
| GoPhish (separate delivery tool) | 3333 | `run_gophish.bat` (optional) |

`Start-PhishAwareness.bat` starts all of them together.

## Manual setup (macOS / Linux, or without the one-click script)

Backend - SQLite, nothing to install:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload            # API on :8000
```

Remediation portal - reuses the same dependencies:

```bash
cd portal
pip install -r requirements.txt
export PA_BASE_URL=http://127.0.0.1:8000
uvicorn app.main:app --port 8100         # portal on :8100
```

Frontend:

```bash
cd frontend
npm install
npm run dev                              # console on :5173
```

Prefer Postgres over SQLite? `docker compose up --build`.

**Packaging a submission.** Zipping the project folder sweeps up `.venv`,
`node_modules`, `.git` and the local databases (~111 MB). Export the tracked
tree instead:

```powershell
.\make-submission.ps1
```

## API (v1)

Auth: `POST /api/v1/auth/login` (OAuth2 password flow; `username` = email) returns
a bearer JWT (algorithm-pinned, expiry-required) **and** sets it as an httpOnly
Secure session cookie; the console uses the cookie, while API/script clients use
the bearer token directly. Cookie-authenticated mutations require a matching
`X-CSRF-Token` header (double-submit against a separate JS-readable cookie) -
bearer-authenticated requests skip that check. All `/tenants/{id}/...` routes are
JWT + RBAC + tenant-scoped; the two public ingestion endpoints are secret-gated.

| Group | Representative endpoints |
|---|---|
| Auth | `POST /auth/login` |
| Dashboards (read) | `GET /tenants/{t}/dashboard/{summary-departments-campaigns-employees-employees/{id}-trend}` |
| Management | `/tenants/{t}/manage/{campaigns-employees-users}` - CSV import/export - `/settings` |
| Directory sync | `/tenants/{t}/manage/integration/directory/{entra-ldap}` - test - preview - import |
| GoPhish control | `/tenants/{t}/manage/gophish/{config-status-campaigns-sync-group-launch-complete-delete}` |
| Portal signals | `/tenants/{t}/portal/employees` - read scores - risk-floor - in-person mark |
| Ingestion (public) | `POST /integrations/gophish/webhook` - `POST /integrations/beacon/events` |

The authoritative, always-current list is the interactive OpenAPI at `/docs`. Roles:
`super_admin`, `org_admin`, `operator`, `dept_viewer` (restricted to their department).

## The scoring model

Three layers plus two secondary metrics and an org overlay. Every constant lives in
`backend/app/scoring/constants.py` for easy re-calibration.

1. **Compromise Depth (CD)** - cumulative points for how far a target went in one
   campaign (opened 2, clicked 15, dwell 5, field-focus 5, typed 10, submitted 30,
   download 15, chatbot up to 30, disclosure 15), capped at 100. Reporting is
   protective: before a click it zeroes the campaign and applies a small negative
   credit; after a click it damps depth to 40%.
2. **Tier coefficient** - `r = CD x T`. The headline **HRS** uses a *severity*
   weighting (Tier-3 hardest lure = 1.6, most dangerous to fall for). The secondary
   **Susceptibility Index** re-weights the same events *inverted* (Tier-1 easiest
   lure = 1.4) - "how easily fooled" - surfacing a different population.
3. **Decayed aggregate** - a 90-day half-life, normalised to 0-100 and banded
   (Low / Moderate / High / Critical). A per-employee `risk_floor` set by the portal
   can raise - never lower - the score for freshly-onboarded staff.

Secondary: **Penetration ratio** = depth reached / deepest reachable for that vector.
Overlay: **Org-risk** = `HRS x role_sensitivity` (Exec 2.0 ... Staff 1.0), kept
*separate* from the individual HRS so titles prioritise attention without penalising
people.

## Documentation

| Doc | What it covers |
|---|---|
| `docs/00_START_HERE.html` | clickable index of everything below |
| `docs/PhishAwareness_Report.docx` / `.pdf` | full technical report (26 pp) |
| `docs/PhishAwareness_Deck.pptx` | defence slide deck (25 slides) |
| `docs/PhishAwareness_Executive_Summary.docx` | plain-language summary |
| `docs/PORTAL_GUIDE.md` | the Awareness & Remediation Portal |
| `docs/INTEGRATIONS_GUIDE.md` | directory sync (Entra/LDAP) + GoPhish control |
| `SECURITY.md` | the secure-coding review and hardening |
| `docs/Administration.md` | admin, migrations, calibration |
| `docs/Evaluation.md` | evaluation plan & results |
| `docs/Capstone2_Spec.md` | the locked design spec |

## Repository layout

```
setup.bat / setup.ps1        one-click Windows install (Python, Node, GoPhish, deps)
Start-PhishAwareness.bat     launch API + console + portal (+ GoPhish)
backend/app/
  scoring/       constants.py engine.py service.py persist.py   the model
  synthetic/     generator.py                                    synthetic events
  db/            base.py models.py                               schema
  api/           routes*.py security*.py schemas.py uploads.py ratelimit.py
  integrations/  gophish_webhook.py gophish_sync.py gophish_admin.py
                 entra.py ldap_dir.py beacon.py                  webhook / sync / directory
  tests/         93 backend tests
backend/eval/    scenarios.py tracking_accuracy.py email_realism.py
backend/migrations/   Alembic migrations
frontend/src/    App.jsx api.js components/*.jsx                 React console
portal/app/      main.py routes_admin.py routes_employee.py      remediation portal
                 remediation.py ticket.py pa_client.py static/   (26 portal tests)
instrumentation/ beacon.js example_landing.html
docs/            report, deck, summary, guides, diagrams
.github/workflows/ci.yml     docker-compose.yml     SECURITY.md
```
