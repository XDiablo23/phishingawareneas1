# GoPhish Runbook - connecting the offensive tool to the scoring platform

This platform is the **measurement layer**. GoPhish (MIT-licensed, separate) is
the **delivery layer** that sends the simulated mail and hosts the landing page.
This runbook is the seam between them: stand up GoPhish, run one internal
campaign, and let its signals flow into scoring.

> **Before anything technical - get approval.** Running a phishing simulation
> against real people, even colleagues, needs explicit written sign-off
> (supervisor / ethics / whoever owns the mailboxes) and a defined consent
> scope. This is non-negotiable and is the longest-lead item. Do it first.

## 0. What connects to what

```
   GoPhish  ──(webhook: opened/clicked/submitted/reported)──►  /integrations/gophish/webhook
   Landing  ──(beacon: dwell/field_focus/typed_no_submit)───►  /integrations/beacon/events
   page                                                             │
                                                                    ▼
                                                        InteractionEvent rows
                                                                    │  Recompute
                                                                    ▼
                                                          HRS / dashboards
```

The webhook gives the backbone; the beacon (see `instrumentation/`) adds the
depth signals GoPhish can't see. You can run with the webhook alone - the depth
ladder just lights fewer rungs.

## 1. Stand up GoPhish

1. Download the release for your OS from the GoPhish project and run it. On
   first start it prints an **admin URL** and a **one-time admin password** in
   the console - copy them.
2. Open the admin UI (default `https://127.0.0.1:3333`), log in, change the
   password.
3. Configure a **Sending Profile** (your test SMTP - use a mail server you're
   authorised to send from) and send a test email to yourself.

## 2. Link a campaign between the two systems

The platform matches GoPhish events to a campaign by **`external_ref`** and to a
person by **email**. So the same identifiers must exist on both sides.

1. In the platform: create the campaign (**Manage -> Campaigns**), set its tier
   and vector. Note the campaign - you'll attach the GoPhish id to it.
2. In GoPhish: create the campaign. After launch, GoPhish assigns it a numeric
   **campaign id** (visible in the URL / dashboard).
3. Back in the platform: set that numeric id as the campaign's `external_ref`
   (via the GoPhish adapter's link call, or the campaign edit form). Now the
   webhook can resolve GoPhish events to this campaign.
4. Roster: the people GoPhish targets must exist in the platform roster with the
   **same email**. Import them (**Manage -> Roster -> CSV import**) using the same
   list you load into GoPhish as a Group.

## 3. Point GoPhish's webhook at the platform

1. Decide a shared secret and set it on the platform side:
   `GOPHISH_WEBHOOK_SECRET=<long-random-string>`.
2. In GoPhish **Settings -> Webhooks**, add:
   - **URL:** `https://<your-host>/api/v1/integrations/gophish/webhook?tenant_id=<tenant-uuid>`
   - **Secret:** the same string. GoPhish signs each POST; the platform verifies
     the `sha256=` signature and rejects mismatches.
3. Enable the webhook. GoPhish will now POST `email_opened`, `clicked_link`,
   `submitted_data`, `email_reported` as they happen.

> The platform **drops any submitted form payload** GoPhish includes - only the
> fact of submission is scored, never the credentials. In GoPhish, also turn
> **Capture Passwords OFF** on the landing page; you never want that data.

## 4. Add the landing beacon (optional but recommended)

Follow `instrumentation/README.md`: paste `example_landing.html` (or your own
page) into the GoPhish landing-page editor, set `window.PHISH_BEACON` with your
`endpoint`, `tenantId`, `token`, and GoPhish's `{{.Email}}` / `{{.CampaignId}}`
template vars, and set `BEACON_INGEST_TOKEN` on the server. This is what
produces dwell / focus / typed-without-submit.

   **Shortcut:** the console's **Manage -> Integration** tab shows your exact
   webhook URL, beacon endpoint, and a ready-to-paste landing snippet, and lets
   an admin generate/rotate the webhook secret and beacon token in place.

## 5. Run it, then score

1. Launch the GoPhish campaign against your consenting group.
2. Watch events arrive (GoPhish timeline; platform audit log shows
   `ingest_gophish_event` / `ingest_beacon_events`).
3. In the platform hit **↻ Recompute** (or let the scheduled job run) to fold
   the new events into HRS. Open **People**, sort by HRS, and drill in - the
   depth ladder and the **HRS trend** now reflect a real campaign.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Webhook returns 401 | secret mismatch | same `GOPHISH_WEBHOOK_SECRET` both sides |
| Events `{"status":"unmapped"}` | campaign/email not linked | set `external_ref`; import the roster with matching emails |
| Beacon 401 | token mismatch | align `BEACON_INGEST_TOKEN` and `PHISH_BEACON.token` |
| Beacon 422 | payload carried a scalar/credential-shaped field | expected - the beacon only sends event type + dwell seconds |
| Scores unchanged after a campaign | not recomputed | **↻ Recompute** or run the scheduled job |
