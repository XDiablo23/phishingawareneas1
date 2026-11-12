# AI-Powered Phishing Awareness & Risk Scoring Platform
## Capstone 2 - Locked Build Specification

**Status:** Planning complete. All design decisions resolved. Ready to build on the start message.
**Team:** Sanad Al-Khatib - Omar Al Sheikh Khalil - Ghassan Hittini - Saad Thibian
**Supervisors:** Dr. Mariam Biltawi - Eng. Sami Al-Mashaqbeh
**Institution:** Al-Hussein Technical University - B.Sc. Cyber Security & Computer Science
**Build window:** Oct 2026 - Feb 2027

This document is the single source of truth. It supersedes anything scattered across planning chats. Every number below (scoring weights, coefficients, caps, thresholds) is intentionally tunable during build, but the *design* is fixed.

---

## 1. What we are building

A proof-of-concept platform that runs realistic, LLM-personalized phishing simulations against an organization's own people, tracks what each person does **beyond the click**, and turns that behaviour into a per-employee human risk score on an admin dashboard. The differentiators versus KnowBe4 / Proofpoint are: (1) hyper-personalized LLM-generated lures instead of static templates, (2) deep multi-stage behavioral tracking, and (3) dynamic, explainable risk scoring with two orthogonal lenses.

**Four core services (from the Capstone 1 design):**
1. **Contextual Profile Database** - org + employee data that seeds the lures.
2. **Generative AI Engine** - turns context into tiered spear-phishing emails and chatbot dialogue.
3. **Simulation Web Application** - hosts cloned landing pages / fake portals / the IT-support chatbot and logs post-click behaviour.
4. **Analytics & Risk Scoring Engine** - converts behaviour into scores and dashboards.

---

## 2. Scope for the graded defense

**In scope (build fully):** one solid, complete customer tenant - end to end - with every table carrying `tenant_id` from day one so multi-tenancy is a later flip, not a rewrite.

**Architected-in but not fully built (deferred):**
- The full two-sided SaaS (an owner/vendor control-plane managing many customer tenants). We ship a *minimal* owner console (add/list/provision a tenant, basic oversight) and design the schema for the rest.
- Outlook "Phish Alert" add-in - documented as a productization feature; the POC uses a monitored report mailbox instead.
- Arabic UI/lures - architected for, demonstrated only if time allows (see §16).

---

## 3. Data schema (Contextual Profile Database)

Three bands with graceful degradation - sparse data simply drops the target to a lower achievable tier rather than failing.

**Employee fields**

| Band | Fields |
|---|---|
| **Hard-required** | `full_name`, `email`, `department`, `job_title` |
| **Strongly recommended** (unlocks Tier 3) | `manager_email` (self-referential), `seniority_level` (Staff / Manager / Director / Exec) |
| **Optional enrichment** | `office_location`, `start_date` (tenure), `primary_tools` (e.g. "M365, Slack, SAP"), `current_projects` (free text), `phone` |

Rule: an employee with no `manager_email` **cannot** receive a manager-impersonation (Tier 3) - the system auto-falls-back to a lower tier for that person.

**Company profile**

| Band | Fields |
|---|---|
| **Required** | `org_name`, `industry`, `sending_domain`, `locale`/`language` |
| **Optional (high value)** | brand assets (`logo_url`, brand color, footer style - feeds landing-page replication), `key_contacts` (CEO/CFO/IT lead/HR lead - prime impersonation targets), `company_events` |

**Company events** (contextual hooks for lures): `title`, `description`, `date`, `tags` (e.g. "O365 migration", "open enrollment", "town hall Thu").

Data is uploaded/seeded per tenant (CSV/DB import). For the POC the "employees" are **persona mailboxes we own** (see §7).

---

## 4. Generative AI Engine

- **POC model:** Google Gemini (strong writing, generous tier, good Arabic).
- **Provider adapter:** the model sits behind a swappable adapter so Gemini / OpenAI / Anthropic / **a customer's own endpoint** are interchangeable. This *is* the "org brings its own model" story.
- **Refusal handling:** hosted models (Gemini included) will sometimes refuse to write phishing content. We (a) use Gemini's per-category safety threshold controls, (b) frame the system prompt as an authorized, sandboxed security-training exercise, and (c) implement a retry path.
- **Local fallback:** an Ollama-hosted open model (Llama/Mistral/Qwen) documented as the escape hatch when the hosted model refuses. This also doubles as a **selling point** - fully offline operation for air-gapped / regulated environments.
- **What the engine generates:** the tiered email body/subject, and the live chatbot dialogue (§10). Landing-page *content* comes from cloning (§8), not the LLM.

---

## 5. Campaign model

**Difficulty tiers**
- **Tier 1 - Generic urgency:** broad templates (password reset, policy update).
- **Tier 2 - Role-based:** tailored to a department (invoices -> finance, CVs -> HR).
- **Tier 3 - Deep contextual impersonation:** mimics the user's actual manager / recent internal events (requires `manager_email`).

**Attack vectors** - a per-campaign `attack_vector` so employees can't pattern-match "our sims always look like X." Options:
- `link_only` - click is the only signal.
- `credential_harvest` - cloned login page captures submission.
- `attachment_download` - a **benign tracked file** (e.g. `Invoice_Q4.pdf`) served from our endpoint; the GET registers a download event; the file is harmless and can carry the "this was a simulation" reveal.
- `chatbot` - fake IT-support chat (§10).
- `mixed` - randomized per recipient across a single campaign.

The vector determines which landing experience loads and therefore which behavioral signals are even reachable (this interacts with scoring - see §11 penetration ratio).

**Audience & scheduling**
- Audience built by filter: random N%, full list, custom by name / department / seniority level, or select-all.
- Audience split into **batches**, each with its own send datetime.
- **Send-window jitter** - each batch is spread over minutes, not fired all at once (realism + deliverability).
- A background scheduler executes batches at their scheduled times. Admin has full control over dates/periods per batch.

---

## 6. Human review gate (revised - sample-based)

Per-email review does not scale (a 3,000-person campaign can't be hand-checked). The gate is:
- **Emails:** the system generates representative **samples per tier/segment**; the admin approves the **template behaviour**, then spot-checks a random N before launch. Approval is of the pattern, not every instance.
- **Landing pages:** **full review** - there are few (one per cloned URL), so every one is approved before it can go live.
- No campaign launches until this approval + a final go is given. A kill switch can halt a running campaign instantly.

---

## 7. Sending architecture - own both ends

- Register one cheap demo domain.
- **Send from** an authenticated sender on that domain (SPF/DKIM/DMARC we control).
- Personas **receive** on a domain we control via **catch-all**, so every `persona@ourdomain` lands in one mailbox we monitor.

Because we operate the receiving mail server, delivery is guaranteed - no consumer spam filter to fight, no email provider suspending us for "phishing simulation" (most ban it by AUP). It is real SMTP end to end, and fully consented because we own every recipient.

**Productization (unchanged):** a paying customer sends from *their own* authenticated domain to *their own* employees, and allowlists the simulation sender in their mail gateway - exactly how commercial platforms operate. Sending to any domain requires **DNS TXT domain verification** first (see §12).

*Note:* email-open tracking is weak over real inboxes; we do not lean on it. All meaningful tracking (click, dwell, field interaction, download, chatbot, report) happens on **our** pages/endpoints where it is reliable.

---

## 8. Landing-page auto-cloning

Admin pastes a URL; the service replicates it. As many as they want; fully automated.

**Mechanism:** a headless browser (Playwright) loads the page, waits for render, serializes the DOM, inlines CSS/images, strips phone-home scripts, **rewrites the form to submit to our capture endpoint**, and injects our telemetry.

**Accepted caveats:**
1. Heavily JS-driven targets (Microsoft, Google) resist cloning and may look slightly off -> we keep a small **library of pre-built templates** as fallback.
2. Cloud providers may flag accounts hosting cloned login pages -> self-host the demo.
3. Every clone passes the **mandatory admin-review gate** before going live.

---

## 9. Behavioral tracking & credential handling

**Signals captured** (JS event listeners -> telemetry API):
- Click, dwell time, credential-field focus, typing-without-submit, form submission, attachment/secondary-link open, chatbot turns and disclosures.
- "Typed without submit" is logged as its own lower-weight signal (some pages capture on input, not just submit).

**Credential handling - passwords are NEVER stored (hashed or otherwise).**
- The **Pwned Passwords (HIBP) k-anonymity** check runs **in the browser**: SHA-1 the entered password client-side, send only the first 5 hash characters to HIBP, compare full suffixes locally.
- We persist **only two booleans**: `submitted = true` and `breached = true (seen N times)`.
- **Username** is stored in plaintext (not a secret).
- Delivers the "compromised-password intel" feature with zero credential-harvesting risk - a clean, defensible privacy story.

---

## 10. The IT-support chatbot vector

A fake helpdesk chat widget, LLM-driven, role-playing "IT Support" / "M365 security team." It performs live social engineering - talking the user into revealing a secret (password, MFA/OTP, security answer) through *conversation* rather than a form. Tests a deeper susceptibility than a click.

**Design:** live LLM agent (real back-and-forth), **~6-8 turn cap** (bounds runtime + API cost), goal = elicit a credential/OTP, **each meaningful turn scored** (+8, capped +30), **+15 on disclosure** of a secret.

This is a capability commercial platforms largely lack - a headline novelty of the project.

---

## 11. Scoring system

Two orthogonal outputs from the **same** event data: **HRS** (how dangerous a person is when they fall) and the **Susceptibility Index** (how easily they're fooled). Different people score high on each; they drive different training.

### Layer 1 - per-campaign Compromise Depth (CD), cumulative, capped at 100

| Signal | Points |
|---|---|
| Opened email | 2 (low - unreliable over real inboxes) |
| Clicked the link | 15 |
| Landed + dwell > ~10s | +5 |
| Focused a credential field | +5 |
| Typed into a field, no submit | +10 |
| Submitted the fake form | +30 |
| Opened/"downloaded" a lure attachment or secondary link | +15 |
| Chatbot engagement | +8 per meaningful turn (cap +30) |
| Chatbot secret/OTP disclosure | +15 |
| **Reported (protective)** | Reported before any click -> CD = 0 + protective credit. Reported after clicking -> CD x 0.4 |

### Layer 2 - tier difficulty coefficient (T), Severity view (chosen)
`T1 = 1.0`, `T2 = 1.3`, `T3 = 1.6`. Falling for the hardest, most realistic attack = highest real-world danger.
**Campaign risk:** `r = CD x T`.

### Layer 3 - decaying aggregate -> 0-100 -> band
Campaign risk `r = CD x T` is **capped at 100** - it lands directly on the band scale (a full compromise is Critical on *any* tier; the coefficient accelerates mid-range failures toward the cap). Each campaign's decayed residual is `r - w`, `w = 0.5^(age_days / 90)` (90-day half-life). Recency-weighted so improvement lowers the score:
`HRS_average = sum(r - w) / max(sumw, 1)` (the evidence floor makes a lone stale failure fade in absolute terms) and `HRS_peak = max(r - w)` (worst residual today). Default headline: `HRS = 0.5-peak + 0.5-average` (**blend**; `HRS_AGGREGATION` = `average` | `peak` | `blend`, `HRS_BLEND_ALPHA` tunable) - one credential submit neither hides behind ignored emails nor permanently defines a person.

| Band | Range |
|---|---|
| Low | 0-24 |
| Moderate | 25-49 |
| High | 50-74 |
| Critical | 75-100 |

### Secondary metric A - Penetration Ratio
Corrects cross-campaign fairness given variable vectors (a `link_only` campaign can't reach the depth a `credential_harvest` one can):
`penetration = depth_reached / deepest_reachable_for_that_vector` - "how far did they go relative to how far they *could*."

### Secondary metric B - Susceptibility Index
Answers "who is easiest to fool," which HRS does not. Computed over the same events with **inverted** tier weighting (falling for an *easy* lure counts *more*): suggested `T1 = 1.4`, `T2 = 1.2`, `T3 = 1.0`. A person fooled by a crude Tier-1 lure scores high here even if their HRS is low - they need basic training, whereas a high-HRS/low-susceptibility person needs advanced-threat training.

### Dashboard overlay - Org Risk (kept separate from individual HRS)
`Org Risk = HRS x role_sensitivity` - an exec/finance/IT-admin who fails is a bigger org problem than an intern who fails. This helps admins *prioritize* without punishing individuals for their job title (the individual HRS measures the person only).

### Explainability
Store the full per-campaign event trail. Every score decomposes into plain reasons (e.g. "High because: clicked Tier-1, typed then submitted creds, password was breached"). This is what makes admins trust the numbers and is directly what the "score sanity" evaluation checks.

---

## 12. Guardrails layer (first-class, not an afterthought)

1. **Domain verification** - a tenant must prove control of a domain via DNS TXT before any simulated phishing can be sent to it. This is the control that separates an *authorized training platform* from a *phishing kit*.
2. **Consented-inbox allowlist** (POC) - real simulated phishing only reaches inboxes on an explicit allowlist.
3. **Human-in-the-loop** - sample-approval for emails + full review for landing pages (§6); a hard launch gate.
4. **No real credential storage** - HIBP client-side method (§9).
5. **Immutable audit log** - who generated what, who launched which campaign against whom, every admin action.
6. **Data minimization + retention + tenant isolation** - employee PII scoped per tenant, encrypted at rest, with retention/deletion rules.
7. **Kill switch** - halt any running campaign instantly.

---

## 13. Roles & access

- **Super Admin** (us) - cross-tenant, control-plane.
- **Org Admin / Manager** - full control within a tenant.
- **Campaign Operator / Analyst** - create/launch campaigns, view results; no user or billing management.
- **Departmental Viewer** - read-only, scoped to their own department's scores (pairs with the dashboard's filter-by-department).

---

## 14. Evaluation plan

- **Email realism** - blind Likert ratings from peers/panel, plus a "spot the sim" test where raters try to distinguish AI lures from genuine corporate mail.
- **Score sanity** - scripted scenarios with an expected ordering; verify the algorithm produces monotonic, explainable outputs consistent with the severity choice.
- **Tracking accuracy** - scripted interaction runs performing known actions; verify every event is captured and correctly attributed to the right recipient/campaign; measure false negatives/positives.

Instrument for all three from day one.

---

## 15. Technology stack

- **Backend:** FastAPI (API-first - everything callable as an API).
- **Database:** Postgres, `tenant_id` on every table.
- **Frontend:** React.
- **Scheduler:** background job runner for batched, jittered campaign sends.
- **Adapters:** LLM provider adapter, email/SMTP adapter, landing-page cloner (Playwright).
- **Packaging:** Docker - `docker compose up` runs the whole stack locally; the same containers run on our domain or a cloud VM.
- **Prior art to study:** GoPhish (open-source phishing framework) - reuse its patterns for the boring plumbing (campaigns, tracking, landing pages); spend real effort on the novel parts (LLM personalization, deep tracking, scoring).

---

## 16. Localization

English-first. Architect prompts, templates, and cloning for Arabic from the start. Demonstrate Arabic in the defense only if time allows. (Arabic is a genuine MENA-market differentiator for the product.)

---

## 17. Suggested build ownership

Starting point from the Capstone 1 task table - re-divide as needed once we scope tickets:

| Area | Lead(s) |
|---|---|
| Contextual Profile DB + internal data APIs | Saad |
| Generative AI Engine (integration, prompt tuning, adapter) | Omar + Ghassan |
| Simulation Web App (portals, cloner, chatbot, tracking) | Sanad + Omar |
| Analytics & Risk Scoring Engine | Ghassan + Saad + Sanad |
| Architecture, guardrails, testing, final report | All |

---

## 18. Deferred / future work

- Full two-sided SaaS control-plane (multi-tenant management) - schema-ready, minimal console for the demo.
- Outlook Phish Alert add-in (Office.js manifest, M365-admin-deployed) - report mailbox used for the POC.
- Live multi-tenant flip.
- Arabic demonstration (if not reached in the build window).

---

*End of specification. No open design questions remain. On the start message, implementation begins against this document.*
