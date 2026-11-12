# Awareness & Remediation Portal

A **separate service** that complements the PhishAwareness measurement platform.
It gives employees non-skippable training + exams and org admins a place to
publish policies and watch remediation - and it drives the automatic
consequences of a high risk score by talking to PhishAwareness **over its REST
API** (no shared database).

```
 Employee browser ─┐
                   ├─► Portal (FastAPI :8100, own SQLite)  ──REST──►  PhishAwareness API (:8000)
 Admin browser  ───┘             │                                        (risk scores + signals)
                                 └──webhook──►  Your ticketing system (e.g. Jira)
```

## What it does

* **Sign-up -> onboarding -> Moderate baseline.** A new employee registers, must
  complete mandatory awareness training (non-skippable lesson dwell + a passed
  exam), and only then does the portal push a **Moderate risk floor** into
  PhishAwareness for that person.
* **Failure or new policy -> remediation (automatic).** When PhishAwareness shows
  a person has slipped to **High/Critical**, or an admin publishes a new policy,
  the portal auto-assigns remediation training - escalating along a ladder
  (standard -> extended) on repeat failures. This is fully automatic for High.
* **Stuck too long -> in-person + ticket.** If someone stays High/Critical past
  the configured tolerance, the portal (a) sets a **"needs in-person awareness"**
  mark on that employee in PhishAwareness, and (b) sends a structured JSON
  **ticket** to a webhook you configure (Jira-ready). The portal only sends the
  information; your team decides what the ticket does.

## Run it

The portal reuses the backend's Python 3.12 virtual environment.

```bat
:: from the project root, after the backend venv exists:
run_portal.bat
```

or manually:

```bat
cd portal
..\backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
set PA_BASE_URL=http://127.0.0.1:8000
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

Then open **http://localhost:8100**:

* **Administrator** -> sign in with your **PhishAwareness** operator/admin login
  (the portal verifies it against PhishAwareness and wires the connection).
* **Employee** -> "Create account" and start training.

`Start-PhishAwareness.bat` in the project root starts everything (API, web,
portal, GoPhish) in one double-click.

## Configuration

All optional - the admin can also set the PhishAwareness connection from the
in-app **Settings** screen. See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `PORTAL_PORT` | 8100 | Portal HTTP port |
| `PORTAL_DATABASE_URL` | `sqlite:///./portal.db` | Portal's own DB |
| `PA_BASE_URL` | `http://127.0.0.1:8000` | PhishAwareness API base |
| `PORTAL_ONBOARDING_FLOOR` | 35 | Baseline HRS pushed after onboarding |
| `PORTAL_INPERSON_AFTER_DAYS` | 30 | Days elevated before in-person + ticket |
| `PORTAL_AUTO_SYNC_SECONDS` | 0 | Background escalation loop (launcher sets 300) |

## Tests

```bat
cd portal
..\backend\.venv\Scripts\python.exe -m pytest app/tests -q
```

The suite runs against a fake PhishAwareness, so it proves the whole
escalation flow (onboarding floor, failure remediation, policy remediation,
in-person escalation + ticket) without a live backend.

## Boundary

Like the measurement platform, the portal is **defensive only**. It stores no
lure content and no simulation credentials. Its link to PhishAwareness is three
signals: read a risk score, push a baseline floor, and raise/clear an in-person
mark - all metadata.
