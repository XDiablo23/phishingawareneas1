# Administration, Migrations & Calibration

This covers the operator/admin control surface added on top of the scoring
core, how to manage the database schema, and how to tune the headline score.

## Management (the "Manage" tab / API)

Once signed in as an **operator** or **org admin**, the console gains a
**Manage** tab with three sections:

- **Campaigns** - create, list, update (status, GoPhish link), and delete
  campaigns. A campaign here is a metadata record; link it to a real
  GoPhish campaign by setting its GoPhish campaign id (see
  `GoPhish_Integration.md`), and inbound events are attributed to it.
- **Employees** - add employees individually or **import a CSV roster**;
  update and remove people. Sample: `backend/data/sample_roster.csv`.
- **Users** (org admin only) - provision console accounts, change roles,
  reset passwords, and remove users. New accounts and resets return a
  **one-time password**, shown once for you to share.

Everything is tenant-scoped, role-gated, and written to the audit log.

CSV roster columns: `full_name,email,department,job_title` plus optional
`manager_email,seniority_level` (seniority one of Staff/Manager/Director/
Exec). Existing people are matched by email and updated; new emails are
created. Credential-like columns are rejected.

### Roles at a glance
| Capability | super_admin | org_admin | operator | dept_viewer |
|---|:---:|:---:|:---:|:---:|
| View dashboards | Yes | Yes | Yes | Yes (own dept) |
| Recompute / ingest | Yes | Yes | Yes | - |
| Manage campaigns & roster | Yes | Yes | Yes | - |
| Manage users | Yes | Yes | - | - |
| Export CSV | Yes | Yes | Yes | Yes (own dept) |

## CSV export

The **⬇ Export** button (and `GET /api/v1/tenants/{tid}/manage/export/employees.csv`)
downloads current risk scores. A departmental viewer's export is scoped to
their department.

## Score calibration (HRS aggregation)

The headline HRS can combine a person's campaigns three ways, set via env
(`HRS_AGGREGATION`), addressing the "distribution skews Low" question:

- **`average`** (default) - decay-weighted mean, `sum(r-w)/sum(w)`. Faithful to
  the original spec; a single severe failure is diluted by ignored campaigns.
- **`peak`** - the single worst campaign, so one bad failure always stands
  out and never hides behind good behaviour.
- **`blend`** - `HRS_BLEND_ALPHA-peak + (1-alpha)-average` (alpha default
  0.5); a tunable middle ground.

The susceptibility index always uses the weighted mean. Change the mode in
`.env` (or the environment) and run **Recompute**. Nothing else hard-codes
the choice - all point values remain in `app/scoring/constants.py`.

## Database migrations (Alembic)

For fresh installs the app creates tables on startup, which is convenient
but can't *alter* an existing database. Once real data lives in the DB, use
Alembic instead:

```bash
cd backend
export USE_ALEMBIC=1            # stops the app from create-all on startup
export DATABASE_URL=...         # your real database
alembic upgrade head           # apply migrations
```

When you change the models later:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

The initial migration under `backend/migrations/versions/` matches the
current schema. `render_as_batch` is enabled so ALTERs work on SQLite too.

## Continuous integration

`.github/workflows/ci.yml` runs on push/PR: it installs the backend, runs
the full test suite and the scoring-evaluation gate, and builds the
frontend. Green CI means the scoring properties still hold and the UI still
compiles.



### Scoring recalibration (v0.6)

Two changes fixed the "everything shows Low" problem:

1. **Risk cap replaces ceiling division.** Campaign risk `r = CD x tier`
   now lands directly on the 0-100 band scale, capped at 100. Previously
   `r` was divided by the theoretical maximum (160), which compressed a
   Tier-3 credential submit to 57 ("High", barely) and a Tier-1 submit
   to 36 ("Moderate") - the band labels did not mean what they said.
   Now: T1 submit ~ 57 (High), T3 submit ~ 91 (Critical), click-only
   T3 ~ 27 (Moderate), reporter = 0 (Low).
2. **Blend is the default aggregation** (`HRS_AGGREGATION=blend`,
   alpha 0.5). Half the headline is the worst *decayed residual*
   campaign, half the decayed average - one credential submit no longer
   hides behind seven ignored emails. `average` and `peak` remain
   selectable. An **evidence floor** (sumw floored at 1) makes a lone,
   stale failure fade in absolute terms instead of scoring as if it
   happened yesterday.
