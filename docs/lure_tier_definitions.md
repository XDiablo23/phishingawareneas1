# Lure Difficulty Tiers - Definitions & Scoring Linkage

*PhishAwareness - AI-Powered Phishing Awareness & Risk-Scoring Platform*
*Reference document for the measurement model. This classifies how hard a
simulation lure is to detect and how that difficulty feeds the risk score.
It does not contain, and the platform does not generate, any deployable lure
content - only difficulty **characteristics** and defensive **red flags**.*

---

## 1. Why tiers exist

A phishing simulation is only meaningful if we know **how hard** the lure was.
Falling for a crude, typo-ridden bulk email is not the same signal as falling
for a personalised, well-crafted spear-phish. The platform therefore assigns
every campaign a **difficulty tier (1-3)**, and the scoring engine uses that
tier two different ways:

| View | Coefficient set | Tier 1 | Tier 2 | Tier 3 | Drives |
|------|-----------------|:------:|:------:|:------:|--------|
| **Severity** - how dangerous the failure is | `TIER_SEVERITY` | 1.0 | 1.3 | 1.6 | Human Risk Score (HRS) |
| **Susceptibility** - how "fool-able" the person is | `TIER_SUSCEPTIBILITY` | 1.4 | 1.2 | 1.0 | Susceptibility Index |

The two are deliberately **inverted**:

- **Severity rises with tier.** Being compromised by the hardest, most
  realistic attack is the most dangerous outcome, so Tier 3 carries the
  highest severity weight (1.6). This is the headline HRS.
- **Susceptibility falls with tier.** Being fooled by an *easy* lure that
  most people would spot is a stronger signal that a person is susceptible,
  so Tier 1 carries the highest susceptibility weight (1.4).

A single person can therefore look "moderate" on HRS but "high" on
susceptibility if they keep failing easy lures - which is exactly the nuance a
security-awareness programme wants to surface.

---

## 2. How tier enters the score (worked numbers)

Campaign risk is `r = CompromiseDepth (CD) x tier coefficient`, capped at 100
and placed directly on the band scale (Low 0-24, Moderate 25-49, High 50-74,
Critical 75-100). CD is the sum of the stages a target reached
(`opened` 2, `clicked` 15, `dwell>10s` 5, `field_focus` 5, `typed_no_submit`
10, `submitted` 30, `download` 15, chatbot turns up to 30, `chatbot_disclosure`
15; capped at 100 per campaign).

**Example A - a click and nothing more** (CD = opened 2 + clicked 15 = 17):

| | Tier 1 | Tier 2 | Tier 3 |
|---|:---:|:---:|:---:|
| Severity `r = 17 x t` | 17.0 (Low) | 22.1 (Low) | **27.2 (Moderate)** |

Same behaviour, but clicking a *convincing* Tier-3 lure already reads Moderate,
while clicking an obvious Tier-1 lure stays Low.

**Example B - a full credential submit** (CD = 2+15+5+5+10+30 = 67):

| | Tier 1 | Tier 2 | Tier 3 |
|---|:---:|:---:|:---:|
| Severity `r = 67 x t` (cap 100) | 67.0 (High) | 87.1 (Critical) | **100 (Critical)** |
| Susceptibility `r = 67 x t` (cap 100) | **93.8 (Critical)** | 80.4 (Critical) | 67.0 (High) |

A full compromise is serious on any tier (severity), but on the
**susceptibility** view the *Tier-1* failure is the loudest alarm.

---

## 3. The three tiers

Each tier is defined across the dimensions a trained user (or a detection
control) would actually use to judge an email. The "red flags" column is the
defensive teaching point - what awareness training should get people to notice.

### Tier 1 - Low sophistication (broad, obvious)
**Intent:** baseline hygiene check; catches people who click almost anything.
**Difficulty to detect:** easy - multiple obvious tells.

- **Sender:** clearly wrong or free-mail address; display name unrelated to domain.
- **Personalisation:** none - generic greeting ("Dear user", "Dear customer").
- **Pretext:** implausible or over-the-top (lottery, unexpected refund, "account will be deleted in 24h").
- **Craft:** spelling/grammar errors, distorted logos, inconsistent formatting.
- **Targeting:** bulk, identical to everyone.
- **Typical vectors:** `link_only`, occasionally `credential_harvest` with a crude page.
- **Coefficients:** severity **1.0**, susceptibility **1.4**.
- **A failure here means:** high susceptibility - the person is not applying basic checks.
- **Red flags to teach:** mismatched sender, generic greeting, urgency + reward, visible errors, hover-the-link mismatch.

### Tier 2 - Moderate sophistication (plausible, semi-targeted)
**Intent:** the realistic "everyday" phish most employees actually receive.
**Difficulty to detect:** medium - one or two subtle tells.

- **Sender:** look-alike or plausibly named internal/service sender (e.g. a believable "IT Service Desk").
- **Personalisation:** light - correct first name, department, or a real internal system name.
- **Pretext:** believable and routine (password expiry, shared document, HR form, delivery notice).
- **Craft:** clean copy, correct branding, few if any obvious errors.
- **Targeting:** grouped (by department or role), not one-to-one.
- **Typical vectors:** `credential_harvest`, `attachment_download`, `link_only`.
- **Coefficients:** severity **1.3**, susceptibility **1.2**.
- **A failure here means:** a realistic, worrying gap - this is the tier closest to real-world risk.
- **Red flags to teach:** subtle domain look-alikes, unexpected auth prompts, "verify/re-enter" requests, slight tone/process mismatch.

### Tier 3 - High sophistication (targeted / spear)
**Intent:** measure resilience against a determined, tailored attacker.
**Difficulty to detect:** hard - few or no tells; requires process, not just eye.

- **Sender:** spoofed or precise look-alike domain; may reference a real colleague or manager.
- **Personalisation:** heavy - role, current project, manager's name, recent internal event.
- **Pretext:** context-aware and timely (tied to a real deadline, migration, or announcement).
- **Craft:** professional, indistinguishable copy and branding; correct signatures/footers.
- **Targeting:** individual or small high-value group (execs, finance, admins).
- **Typical vectors:** `credential_harvest`, `attachment_download`, `chatbot`.
- **Coefficients:** severity **1.6**, susceptibility **1.0**.
- **A failure here means:** maximum severity - even careful people can fall, and the blast radius is large.
- **Red flags to teach:** out-of-band verification for sensitive actions, "does this request fit our process?", scrutiny of authentication and payment/credential requests regardless of how legitimate the message looks.

---

## 4. Tier x vector reference

The **penetration ratio** (depth reached / deepest reachable for that vector)
uses the reachable-event map below, so a lure's vector bounds how deep a target
can go. Tier is independent of vector - it scales whatever depth was reached.

| Vector | Reachable stages | Deepest CD | Notes |
|--------|------------------|:----------:|-------|
| `link_only` | opened, clicked | 17 | Awareness/click-rate only; no credential surface. |
| `credential_harvest` | opened, clicked, dwell, field_focus, typed_no_submit, submitted | 67 | Full behavioural ladder; the beacon lights the middle rungs. |
| `attachment_download` | opened, clicked, download | 32 | Models malware-delivery style lures. |
| `chatbot` | opened, clicked, chatbot_turn (<=30), chatbot_disclosure | 62 | Conversational/social-engineering channel. |
| `mixed` | resolved per target to a concrete vector before scoring | - | Each recipient gets one of the above (`effective_tier`/`assigned_vector`). |

---

## 5. Setting the tier in the platform

- Each campaign carries a `tier` (1-3) and an `attack_vector`, set under
  **Manage -> Campaigns** (or synced from GoPhish, where the operator refines it).
- `mixed` campaigns randomise a concrete vector per recipient; the resolved
  `effective_tier` and `assigned_vector` on each `campaign_target` are what the
  engine actually scores.
- The tier is a **design decision made when the lure is authored** (in GoPhish),
  recorded here for measurement. The platform never generates or rates the lure
  content itself - it scores the behaviour that comes back.

---

## 6. Calibration & defensibility

- Coefficients live in `backend/app/scoring/constants.py` and are the single
  place to re-tune the model - no logic changes needed.
- The inverted susceptibility view is the defensible core of the design: it
  separates *"dangerous when it happens"* (severity/HRS) from *"likely to
  happen"* (susceptibility), so a programme can act on both.
- Because tier only ever scales **observed behaviour**, and job title is kept
  out of the individual HRS (it lives in the separate Org-Risk overlay), no one
  is penalised for who they are - only for what they did against a lure of a
  known difficulty.

---

## 7. Per-vector Compromise-Depth breakdown

The penetration ratio's denominator (`vector_max_depth`) is the sum of the CD
points for exactly the stages that vector can reach. Making the arithmetic
explicit:

| Vector | opened 2 | clicked 15 | dwell 5 | field_focus 5 | typed 10 | submitted 30 | download 15 | chatbot_turn <=30 | chatbot_disc 15 | **Max CD** |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `link_only` | ✓ | ✓ | | | | | | | | **17** |
| `credential_harvest` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | | **67** |
| `attachment_download` | ✓ | ✓ | | | | | ✓ | | | **32** |
| `chatbot` | ✓ | ✓ | | | | | | ✓ | ✓ | **62** |

`chatbot_turn` contributes the capped total (`CHATBOT_TURN_CAP = 30`), not a
single turn's 8 points. `mixed` has no fixed denominator - each recipient is
resolved to one concrete vector (`assigned_vector`) before scoring, and that
vector's Max CD is used.

`download`, `chatbot_turn`, and `chatbot_disclosure` don't come from GoPhish
or the landing-page beacon - see
[`GoPhish_Integration.md`](GoPhish_Integration.md) §6 for a worked example of
how to emit them from your own attachment-tracking or chatbot-simulator
surface via the standard ingestion endpoint.

## 8. Penetration ratio - worked examples

`penetration_ratio = depth_reached / vector_max_depth` (0-1). It answers "how
far did they go relative to how far this lure *could* take them" - orthogonal to
severity (absolute danger).

| Scenario | Stages reached | depth | vector max | penetration |
|---|---|:--:|:--:|:--:|
| Credential lure, clicked + dwelled + focused, no submit | 2+15+5+5 | 27 | 67 | **0.40** |
| Credential lure, full submit | 2+15+5+5+10+30 | 67 | 67 | **1.00** |
| Link-only lure, clicked | 2+15 | 17 | 17 | **1.00** |
| Attachment lure, opened + clicked, no download | 2+15 | 17 | 32 | **0.53** |

Note the contrast in rows 2-3: a link-only click *maxes* penetration (1.00) yet
carries low absolute severity (`r = 17 x tier`), while a credential submit also
reaches 1.00 but with far higher severity (`r = 67 x tier`). Penetration
measures *thoroughness within a vector*; severity/HRS measures *danger*. Both are
reported so an operator can tell "went all the way on a weak lure" from "went all
the way on a dangerous one".

## 9. Edge cases & interactions

- **Reporting before any click** zeroes CD (hence penetration = 0) regardless of
  tier, and applies the `-10` protective credit to the campaign's severity risk.
- **Reporting after a click** multiplies accumulated CD by `0.4` *before* the
  tier coefficient and before penetration is computed.
- **Decay** applies to the post-tier campaign risk `r`, not to CD; penetration
  always uses the raw (un-decayed) depth, so it describes what happened in that
  campaign at the time.
- **Tier and vector are independent axes:** tier scales the *risk* of whatever
  depth was reached; vector bounds *how much depth is reachable*. A Tier-3
  `link_only` lure can still only reach CD 17 - targeting difficulty does not
  add rungs to the ladder, it re-weights them.
