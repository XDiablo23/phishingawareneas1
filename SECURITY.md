# Security Review & Secure-Coding Notes

*PhishAwareness - AI-Powered Phishing Awareness & Risk-Scoring Platform*
*Covers the measurement backend, the Awareness & Remediation Portal, and the
web console. This document records the trust model, the controls in place, the
hardening applied in the secure-coding pass, the residual/accepted risks, and a
production deployment checklist.*

---

## 1. Scope & method

Reviewed for: authentication & session handling, authorization + multi-tenant
isolation, injection (SQL / LDAP / CSV), SSRF, secret handling, input
validation, file uploads, rate limiting, transport/response-header hardening,
error/information disclosure, cross-site scripting, and dependency risk.

The review covered `backend/` (FastAPI measurement API), `portal/` (the
separate FastAPI training/remediation service), and `frontend/` (the React
console) plus the vanilla-JS portal SPA. Findings were fixed in code and locked
in with regression tests (`backend/app/tests/test_security.py`,
`portal/app/tests/test_security.py`).

## 2. Trust boundaries

| Actor | How they authenticate | Can reach |
|---|---|---|
| Console user (org_admin / operator / dept_viewer) | PhishAwareness login -> JWT | Their **own tenant** only (super_admin excepted) |
| Portal employee | Native portal account (PBKDF2 + JWT) | Their own training only |
| Portal admin | **Delegated** to a PhishAwareness login | The single connected org |
| GoPhish server | HMAC-signed webhook | Post event *metadata* for one tenant |
| Landing page beacon | Shared ingest token | Post event *metadata* for one tenant |
| The two services to each other | Per-tenant service token over REST (`X-Portal-Token`) | The `/portal` signal surface only |

Everything an authenticated user reaches is scoped to their tenant by
`enforce_tenant`, and a departmental viewer is further scoped to their own
department. The measurement core **never stores credentials** - by construction
there is no password/secret column on the event path, and the ingestion
endpoints actively reject credential-shaped fields.

## 3. Controls already in place (verified)

- **Passwords:** PBKDF2-HMAC-SHA256, 200k rounds, per-user 16-byte salt,
  compared with `hmac.compare_digest` (constant-time). Both services.
- **Sessions:** stateless JWT (HS256) with a pinned algorithm on decode and a
  short TTL. Secrets never leave the server. The browser console holds the
  session in an **httpOnly Secure cookie** (`access_token`) rather than
  `localStorage` - an XSS payload can no longer read or exfiltrate it.
  State-changing requests authenticated this way require a matching
  `X-CSRF-Token` header against a separate, JS-readable `csrf_token` cookie
  (double-submit pattern, `backend/app/api/csrf.py`); a request carrying its
  own `Authorization: Bearer` header (API/script clients, per the curl
  examples in `docs/GoPhish_Integration.md`) skips the CSRF check entirely,
  since a cross-origin page cannot forge that header without a CORS grant.
  `POST /auth/logout` clears both cookies. In production both cookies are
  `SameSite=None` (paired with `Secure`, which `None` requires) rather than
  `Lax`, because a `Lax` cookie is never attached to a cross-site fetch/XHR
  at all - only to top-level navigation - which would silently break the
  documented split-origin deployment (`VITE_API_BASE` on a separate origin
  from the API, see `CORS_ORIGINS`/`allow_credentials` below) regardless of
  the CORS grant. This is safe because CSRF is enforced explicitly via the
  token check above, not relied upon implicitly via `SameSite`. Local dev
  stays `Lax` (same-origin through the Vite proxy, no HTTPS required).
- **AuthZ:** role dependencies (`require_roles`) + per-tenant enforcement +
  department scoping. Destructive actions (delete campaign, delete user) are
  admin-only.
- **SQL injection:** all data access is through SQLAlchemy ORM / parameterized
  queries; no string-built SQL.
- **Inbound ingestion:** the GoPhish webhook is HMAC-verified (timing-safe); the
  landing beacon is token-gated. Both store **metadata only**, discard any
  submitted form payload, and reject credential-shaped fields. Both are behind
  the per-IP rate limiter.
- **Secrets:** integration secrets (webhook/beacon/GoPhish/Entra/LDAP/portal
  service token) are stored write-only - status is exposed as a boolean,
  values are shown once at most (on rotate), and never logged (audit records
  booleans). Every one of these is also **encrypted at rest** with Fernet -
  the six backend Tenant columns (`webhook_secret`, `ingest_token`,
  `gophish_api_key`, `entra_client_secret`, `ldap_bind_password`,
  `portal_service_token`; `backend/app/crypto.py`) and the portal's own
  `Setting.pa_service_token` and `TicketConfig.auth_header_value`
  (`portal/app/crypto.py`) - so a database dump or backup never exposes
  these in the clear, not just the API responses. The portal has no
  Alembic; an idempotent startup step (`ensure_secrets_encrypted`,
  called from the lifespan alongside the existing seed step) backfills any
  legacy plaintext value on boot.
- **Least-privilege service auth:** the portal's background automation
  authenticates to the `/portal` signal surface with a dedicated, rotatable,
  per-tenant token (`X-Portal-Token`) rather than a human operator/admin
  login - a leaked token can reach only those five endpoints, not campaign
  launch, roster, or user management. The portal's interactive admin login
  is a separate, unrelated delegated-auth check against PhishAwareness that
  persists nothing.
- **Observability of withheld detail:** the ingestion endpoints answer an
  unresolvable campaign/recipient with a generic reason code only
  (`campaign_not_linked` / `employee_not_found`), because echoing the
  looked-up email back would make a secret-gated endpoint a roster-
  enumeration oracle. The identifiers an operator needs are still recorded
  where only legitimate access can read them: both paths log them
  (`app/logging_config.py`), and the **HMAC-verified** GoPhish webhook also
  writes an `AuditLog` row. The beacon path deliberately writes no audit
  row - its token is embedded in a public landing page, so a row per
  request would let any reader of that page append unbounded rows to the
  tenant's audit trail. A rotated log absorbs that; the audit table cannot.
- **Upgrade hygiene:** credentials superseded by a design change are
  actively scrubbed, not merely abandoned. A `portal.db` created before the
  service-token change still held the operator's email and *plaintext
  password* in the columns the token replaced; nothing read them, and the
  encryption backfill only covers columns still in the model, so they would
  have survived indefinitely. The portal's startup schema patch now blanks
  both (blanking rather than `DROP COLUMN`: it works below SQLite 3.35 and
  does not rewrite the table).
- **Validation:** Pydantic models enforce types, enums, and length caps
  throughout; a forbidden-key guard blocks credential-like fields.


## 4. Hardening applied in this pass

**Transport / headers**
- Added a **security-headers** middleware to both services: `X-Content-Type-
  Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, and a **Content-Security-Policy** (`default-src 'none'`
  on the JSON API; a locked, self+inline policy on the portal SPA with
  `frame-ancestors 'none'`, `object-src 'none'`, `base-uri`). `Strict-Transport-
  Security` is emitted in production. API responses are `Cache-Control: no-store`.
- **Interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are disabled in
  production** on both services.

**Auth / sessions**
- JWT decode now **requires an `exp` claim** (and still pins the algorithm), so a
  token with no/stale expiry - or one forged under a different alg/key - is
  rejected. Both services.
- The portal now has a **production secret fail-fast** (mirrors the backend):
  it refuses to start under `PORTAL_ENV=production` on the dev secret.
- Added a **per-IP rate limiter on the portal auth endpoints** (register / login
  / admin-login) to blunt credential brute-forcing.

**Injection / integrity**
- **CSV export** now neutralises spreadsheet **formula injection** (cells that
  begin with `= + - @` or a control char are quoted).
- **Event ingestion** (JSON + CSV) now rejects events that reference a campaign
  or employee **outside the caller's tenant**, closing a cross-tenant integrity
  gap, and the CSV parser is per-row fault-tolerant (a malformed row is counted,
  never a 500).
- **LDAP** search uses an admin-set filter with **no user-supplied
  interpolation**, so there is no LDAP-filter injection surface.

**File uploads**
- All uploads are **size-capped** (event/roster CSV via `MAX_UPLOAD_MB`, default
  10 MB; portal policy docs 15 MB) so a large file can't exhaust memory.
- Portal policy uploads are **extension-allowlisted** and the stored filename is
  **sanitised** (basename + safe charset), preventing path traversal.

**XSS**
- Admin-authored **lesson / policy HTML is sanitised server-side** through an
  allowlist parser (`portal/app/sanitize.py`): formatting tags are kept;
  `<script>`, `<iframe>`, event-handler attributes, inline styles and
  `javascript:` links are stripped. Module **resource/embed URLs are restricted
  to http(s)**.

**SSRF surface**
- Operator-configured outbound URLs are **scheme-validated**: the portal ticket
  webhook and PA connection must be `http(s)`, the GoPhish base URL `http(s)`,
  and the LDAP URI `ldap(s)`. These endpoints remain admin/operator-gated and
  audit-logged (see §5).

**Fail-closed in production**
- The GoPhish webhook and the landing beacon **reject unsigned/untokened
  requests in production** (they stay permissive only in development, where no
  secret is configured).


## 5. Residual & accepted risks

- **SSRF by design.** The whole point of the integrations is that an operator
  points the platform at *their* GoPhish server, *their* directory, and *their*
  ticketing webhook - some of which are internal hosts. We scheme-validate and
  gate these to admin/operator + audit them, but we do not (and cannot) block
  internal targets without breaking the feature. In a locked-down deployment,
  put the services behind an **egress allowlist / proxy** so they can reach only
  the intended integration hosts.
- **Admin-authored HTML.** Portal admins can write lesson/policy HTML that other
  employees view. It is sanitised (§4), and admins are trusted operators
  (verified against PhishAwareness), so this is a low-severity, defence-in-depth
  item rather than an open XSS.
- **Portal service credential - resolved.** Background escalation used to run
  on a stored operator/admin login, so a compromised portal process carried
  the full operator blast radius. It now authenticates with a dedicated,
  minimally-scoped, rotatable token limited to the `/portal` signal surface
  (see §3, "Least-privilege service auth") - moved here from an accepted
  risk to a verified control.
- **GoPhish TLS.** GoPhish ships a self-signed admin cert, so `GOPHISH_VERIFY_TLS`
  defaults off for the local admin API. Set it **on** with a real certificate in
  production. This is now a **per-tenant** setting (Manage -> Integration ->
  GoPhish sync), not just a server-wide env var - each tenant verifies (or
  skips) TLS against its own GoPhish server independently, so one tenant's
  self-signed cert can't force every other tenant sharing this deployment to
  also disable verification.
- **Stateless JWTs** cannot be revoked before expiry; the TTL is short. Add a
  denylist/rotation if instant revocation becomes a requirement.

## 6. Production deployment checklist

- [ ] `ENV=production` (backend) and `PORTAL_ENV=production` (portal).
- [ ] Strong random `SECRET_KEY` and `PORTAL_SECRET_KEY` (both fail-fast on the
      dev default in production).
- [ ] Strong random `ENCRYPTION_KEY` (backend) and `PORTAL_ENCRYPTION_KEY`
      (portal) - both fail-fast on the dev default in production - the
      Fernet keys protecting every secret column at rest.
- [ ] `CORS_ORIGINS` set to the real console origin(s); portal CORS left closed
      unless a separate origin is needed.
- [ ] `RATE_LIMIT_PER_MINUTE` (backend) and `PORTAL_RATE_LIMIT_PER_MINUTE` set
      (e.g. 60 / 30).
- [ ] Per-tenant **webhook secret** and **beacon ingest token** configured (the
      endpoints fail closed in production otherwise).
- [ ] `GOPHISH_VERIFY_TLS=1` (server default) with a valid certificate; override
      per tenant under Manage -> Integration if a specific tenant's GoPhish
      server needs a different setting.
- [ ] Terminate **TLS** at a reverse proxy and cap request **body size** there
      too (belt-and-braces with `MAX_UPLOAD_MB`).
- [ ] Run behind an **egress allowlist** for the integration hosts (see §5).
- [ ] Use a managed database (Postgres) and back it up; keep the audit log.

## 7. Testing & dependency audit

- **119 automated tests pass** (93 backend + 26 portal), including a dedicated
  security regression suite: response headers, JWT expiry/alg/key enforcement,
  CSV formula-injection escaping, the HTML sanitizer, cross-tenant event
  rejection, outbound-URL scheme validation, secret encryption/backfill,
  session-cookie + CSRF behaviour, and the portal service token.
- **`pip-audit`: no known vulnerabilities** in the backend dependency set at the
  time of review. Re-run it in CI on every dependency change.

## 8. Reporting

This is an academic Capstone project. For a real deployment, add a
`SECURITY.md` contact and a coordinated-disclosure policy, and wire `pip-audit`
(and `npm audit` for the console) into CI.
