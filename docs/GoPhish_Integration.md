# GoPhish Integration Guide

This platform is the **scoring and analytics** layer. The phishing
simulation itself - sending mail, hosting landing pages, tracking clicks -
is run by **GoPhish** (MIT-licensed, purpose-built for authorised
simulations). This guide connects the two: GoPhish emits a webhook per
recipient event, and the adapter here translates those events into the
scoring pipeline.

```
   ┌────────────┐   webhook per event    ┌───────────────────────────┐
   │  GoPhish   │ ─────────────────────► │  /integrations/gophish/    │
   │ (engine)   │  Opened/Clicked/       │  webhook  (this platform)  │
   │            │  Submitted/Reported    │  -> scoring pipeline        │
   └────────────┘                        └───────────────────────────┘
```

## 1. Prerequisites

- A running GoPhish instance used strictly for **authorised** simulations
  against consented recipients / mailboxes your team controls.
- This platform running and reachable from GoPhish over HTTPS.
- The employees you'll target already loaded here (their `email` must match
  the recipient email GoPhish uses - that's the join key).

## 2. Recommended GoPhish hardening

**Disable password capture in GoPhish.** When building a landing page,
leave **"Capture Passwords"** unchecked (you can keep "Capture Submitted
Data" to know a submission happened). This platform never needs the typed
credential - only the fact that a submission occurred. The adapter also
**drops any captured payload** it receives (defence in depth), but turning
it off at the source is the right default for a privacy-respecting program.

## 3. Configure the webhook

In GoPhish -> **Webhooks** -> New:

- **URL:** `https://<your-console-host>/api/v1/integrations/gophish/webhook?tenant_id=<TENANT_ID>`
- **Secret:** a long random string.

Then set the same secret on this platform so inbound signatures are
verified:

```bash
export GOPHISH_WEBHOOK_SECRET="<the same secret>"
```

If the secret is unset here, signatures are **not** verified - acceptable
for local testing only. GoPhish signs each request with
`X-Gophish-Signature: sha256=<hmac-sha256 of the raw body>`; the adapter
validates it with a constant-time comparison.

## 4. Link each GoPhish campaign to a local campaign

GoPhish identifies campaigns by a numeric `campaign_id`. Associate it with
the corresponding local campaign once, as an operator or org-admin:

```bash
curl -X POST https://<host>/api/v1/tenants/<TID>/campaigns/<LOCAL_CAMPAIGN_ID>/link \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"external_ref": "<gophish_campaign_id>"}'
```

Inbound events whose `campaign_id` has no linked local campaign are
acknowledged but not stored (the response says so), so GoPhish won't
retry-storm while you fix the link.

## 5. Event mapping

| GoPhish event   | Stored event type | Notes |
|-----------------|-------------------|-------|
| `Email Opened`  | `opened`          | open-pixel; unreliable, low weight |
| `Clicked Link`  | `clicked`         | |
| `Submitted Data`| `submitted`       | **payload discarded**; only the fact is kept |
| `Email Reported`| `reported`        | protective - lowers risk |
| `Email Sent`    | *(ignored)*       | no scoring signal |
| `Error Sending Email` | *(ignored)* | |
| `Proxied request` | *(ignored)*     | |

Dwell time, field-focus, typed-no-submit, download, and chatbot events are
richer signals than GoPhish emits natively. If you instrument your landing
pages to send those, POST them to the standard ingestion endpoints
(`/tenants/{tid}/events` or `/events/csv`) using the same event-type names;
they'll score identically.

## 6. Extending beyond GoPhish: download & chatbot signals

Two of the model's vectors - `attachment_download` and `chatbot` (see
[`lure_tier_definitions.md`](lure_tier_definitions.md)) - need signals GoPhish
never emits and the landing-page beacon deliberately doesn't accept either:
`download`, `chatbot_turn`, and `chatbot_disclosure` are excluded from
`ALLOWED_EVENTS` in `backend/app/integrations/beacon.py` on purpose, because
that endpoint is a public, token-only surface meant only for the passive
signals a landing page can observe by itself.

These richer events are expected to come from **your own instrumented
surface** instead - a tracked download link/redirect for an
`attachment_download` lure, or a chatbot-simulator backend for a `chatbot`
lure - something that can hold a real operator/org-admin credential and call
the same authenticated ingestion endpoint everything else here uses:

```bash
curl -X POST https://<host>/api/v1/tenants/<TID>/events \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{
    "events": [
      {"campaign_id": "<CAMPAIGN_ID>", "employee_id": "<EMPLOYEE_ID>", "event_type": "download"},
      {"campaign_id": "<CAMPAIGN_ID>", "employee_id": "<EMPLOYEE_ID>", "event_type": "chatbot_turn"},
      {"campaign_id": "<CAMPAIGN_ID>", "employee_id": "<EMPLOYEE_ID>", "event_type": "chatbot_turn"},
      {"campaign_id": "<CAMPAIGN_ID>", "employee_id": "<EMPLOYEE_ID>", "event_type": "chatbot_disclosure"}
    ]
  }'
```

`campaign_id`/`employee_id` are this platform's own internal IDs (the same
ones from `/manage/campaigns` and `/manage/employees`), not GoPhish's numeric
IDs - same join convention as everywhere else in this guide. As with every
other event type, no free-text content is accepted: send one event per
occurrence and nothing else. If you attach `event_metadata`, it goes through
the same credential-field filter as the rest of the schema (`app/api/schemas.py`).

| `event_type`          | Meaning                                    | Points toward Compromise Depth |
|------------------------|--------------------------------------------|:---:|
| `download`             | opened/downloaded the lure attachment      | 15 (flat) |
| `chatbot_turn`         | one meaningful reply in the chatbot        | 8 per turn, capped at 30 total |
| `chatbot_disclosure`   | disclosed a secret/OTP to the chatbot      | 15 (flat) |

See [`lure_tier_definitions.md`](lure_tier_definitions.md) §7-8 for how these
points combine with tier and vector into the full Compromise Depth and
penetration-ratio math - the worked examples there cover both vectors end to
end.

## 7. Recompute scores

Events accumulate as they arrive. Scores are recomputed on demand so a run
is scored as a batch:

```bash
curl -X POST https://<host>/api/v1/tenants/<TID>/recompute \
  -H "Authorization: Bearer <token>"
```

Run it after a campaign completes, or on a schedule (e.g. a cron / task
that calls `recompute` every few minutes during an active campaign).

## 8. Verifying the connection

- GoPhish -> Webhooks -> **Ping** should return success once the URL/secret
  are set.
- Send yourself a test email from a small GoPhish campaign, click it, and
  confirm the event appears (the webhook response is `{"status":"recorded"}`)
  and the person's score moves after a `recompute`.

## What the adapter deliberately does NOT do

It does not send mail, render or clone pages, or store credentials. It is a
one-way translator from GoPhish's event notifications into interaction
metadata. The offensive/simulation surface stays entirely in GoPhish, which
you operate under your own authorisation and rules of engagement.
