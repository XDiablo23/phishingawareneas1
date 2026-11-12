# Operator Integrations - Azure AD Directory & GoPhish Control

*PhishAwareness - AI-Powered Phishing Awareness & Risk-Scoring Platform*
*Two operator-facing integrations that let an org populate its roster from
Azure AD and run the full GoPhish campaign lifecycle from this console.*

---

## 1. What was added, and the boundary

The measurement core is unchanged and still boundary-clean: it scores event
metadata and never stores credentials. These two features sit **around** that
core as an explicit, authorized **operator capability**:

* **Directory sync (Azure AD / Entra ID *or* on-prem Active Directory / LDAP)**
  - import people into the employee roster from Microsoft Entra ID or from an
  on-prem domain controller. Reads directory *metadata only*.
* **GoPhish campaign control** - build target groups from the roster and
  create / launch / schedule / complete / delete campaigns from our UI.

Where earlier the GoPhish link was read-only, the console can now drive the
campaign lifecycle. One line is held deliberately: the **email templates and
landing pages are authored inside GoPhish**, and this console only *selects and
uses* them - it does not compose lures or clone/credential-capture pages, and it
never receives or stores what a target types. Launches are **authorization-gated
and audit-logged**, and the UI warns if a chosen landing page captures passwords.

Both integrations live under **Manage -> Integration**, are tenant-scoped, and
are RBAC-gated (config is admin-only; sync/launch is operator+admin; delete is
admin-only).

---

## 2. Azure AD (Entra ID) directory sync

### What it does
Pulls users from Microsoft Graph and upserts them into the roster
(idempotent by email): full name, email, department, job title, office, and a
**seniority guess** derived from the job title (Exec / Director / Manager /
Staff - which feeds the Org-Risk overlay). It reads directory metadata only; no
user credentials are ever read or stored.

### One-time setup (Entra app registration)
1. In the Azure portal -> **Microsoft Entra ID -> App registrations -> New
   registration**. Name it e.g. "PhishAwareness Directory Reader".
2. **API permissions -> Add a permission -> Microsoft Graph -> Application
   permissions ->** `User.Read.All` (or `Directory.Read.All`). Then **Grant
   admin consent**.
3. **Certificates & secrets -> New client secret.** Copy the secret *value*.
4. Copy the **Directory (tenant) ID** and the **Application (client) ID** from
   the app's Overview.

### Configure and import
In **Manage -> Integration -> Directory sync**:
1. Paste the tenant ID/domain, client ID, and client secret -> **Save & test**
   (a green "connected" state means Graph is reachable).
2. **Preview** shows the first users mapped to roster fields - sanity-check the
   mapping.
3. **Import users** upserts the whole directory into the roster, then run a
   **Recompute** so any new hires are scored.

Server env fallback (optional): `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`,
`ENTRA_CLIENT_SECRET`.


---

## 2b. On-prem Active Directory (LDAP)

For organizations that run **on-prem AD** instead of (or alongside) Entra, the
same Directory panel has an **On-prem AD (LDAP)** tab. It binds to a domain
controller with a read-only service account and searches for users, mapping the
same fields into the roster:

| AD attribute | Roster field |
|---|---|
| `displayName` | full name |
| `mail` (or `userPrincipalName`) | email (join key) |
| `department` | department |
| `title` | job title (+ seniority guess) |
| `physicalDeliveryOfficeName` | office |

### Configure and import
In **Manage -> Integration -> Directory sync -> On-prem AD (LDAP)**:
1. **LDAP server URI** - `ldap://dc.corp.local:389` (prefer `ldaps://...:636` in
   production).
2. **Bind DN** - a **read-only** service account (`svc-directory@corp.local` or
   its full DN).
3. **Bind password** - stored write-only.
4. **Search base DN** - e.g. `DC=corp,DC=local`.
5. **User filter** *(optional)* - defaults to
   `(&(objectClass=user)(objectCategory=person))`.

Then **Save & test** (a green "bound" state), **Preview**, and **Import users**
- identical to the Entra flow, and idempotent by email so you can run both a
directory sync and a GoPhish group push in sequence. It reads metadata only and
never reads anyone's password. Uses the pure-Python `ldap3` library (no system
dependencies). Server env fallback: `LDAP_URI`, `LDAP_BIND_DN`,
`LDAP_BIND_PASSWORD`, `LDAP_BASE_DN`, `LDAP_USER_FILTER`.

---

## 3. GoPhish campaign control

### What it does
Orchestrates GoPhish's REST API so the org runs everything from one console:

* **Groups from roster** - push a GoPhish target group built from your roster
  (everyone, a department, or an explicit subset). Idempotent by group name, so
  a directory re-sync + re-push keeps GoPhish in step.
* **Launch a campaign** - pick an existing **email template**, **landing page**
  and **sending profile** (all authored in GoPhish), a **target group**, and a
  **phishing URL**, then launch now or schedule a launch date. The console also
  creates a linked local campaign (with the tier/vector you set) so results flow
  straight into scoring.
* **Lifecycle controls** - **Complete** or **Delete** a campaign from the
  campaign table.

### Setup
Set the GoPhish admin URL + API key under **Manage -> Integration -> GoPhish sync**
(GoPhish -> Settings -> API key). The same connection powers both the read-only
sync and this control surface.

### Guardrails (built in)
* **Authorization gate** - a launch requires ticking *"I confirm this phishing
  simulation is authorized for these recipients."* The API rejects a launch
  without it (HTTP 422), and the confirmation is recorded in the audit log.
* **Audit log** - every group push, launch, complete and delete is written to
  the audit log with the actor, campaign, and content used.
* **No-password-capture default** - landing pages are listed with their GoPhish
  capture flags; if you pick one with *Capture Passwords* on, the console shows a
  prominent warning. (This platform never receives or stores those values
  regardless - the boundary is structural.)
* **Content stays in GoPhish** - the console never creates or clones templates
  or landing pages; it only references what the operator authored in GoPhish.

### Scoring linkage
A launched campaign is linked to a local campaign by GoPhish id (`external_ref`).
As GoPhish records opens/clicks/submits, the existing **GoPhish sync** (or the
webhook) pulls that event *metadata* in and the engine scores it - so a campaign
you launched here shows up on the dashboards automatically.

---

## 4. API reference (all under `/api/v1/tenants/{tenant_id}/manage`)

| Method + path | Role | Purpose |
|---|---|---|
| `POST /integration/entra/config` | admin | Set Entra tenant/client/secret |
| `GET  /integration/entra/status` | operator | Test the Graph connection |
| `GET  /integration/entra/preview` | operator | Sample mapped users (no writes) |
| `POST /integration/entra/sync` | operator | Import/refresh the roster (Entra) |
| `POST /integration/ldap/config` | admin | Set LDAP uri/bind/base/filter |
| `GET  /integration/ldap/status` | operator | Test the LDAP bind |
| `GET  /integration/ldap/preview` | operator | Sample mapped users (no writes) |
| `POST /integration/ldap/sync` | operator | Import/refresh the roster (on-prem AD) |
| `GET  /integration/gophish/templates \| pages \| smtp \| groups` | operator | Pickers (read) |
| `POST /integration/gophish/groups/from-roster` | operator | Push a group from the roster |
| `POST /integration/gophish/campaigns/launch` | operator | Create/launch (authorization-gated) |
| `POST /integration/gophish/campaigns/{id}/complete` | operator | Mark complete |
| `DELETE /integration/gophish/campaigns/{id}` | admin | Delete in GoPhish |

---

## 5. Testing

`backend/app/tests/test_directory_gophish.py` mocks only the network boundary
(Microsoft Graph, the LDAP directory, and the GoPhish REST API), so it exercises
the real mapping, roster upsert, group-building, campaign linking, the
authorization gate, the password-capture warning, and RBAC. All backend tests
pass (93/93), and a live smoke confirms the running server serves the endpoints
and enforces the launch gate (422 without authorization).
