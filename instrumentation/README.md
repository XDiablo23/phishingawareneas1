# Landing-page instrumentation

The scoring platform grades *interaction metadata*. GoPhish supplies the coarse
backbone (opened / clicked / submitted / reported) through its webhook. This kit
supplies the finer signals GoPhish cannot observe, which are what make the
compromise-depth ladder meaningful:

| Signal | Emitted when | Depth points |
|---|---|---|
| `clicked` | landing page loads (the click-through) | 15 |
| `dwell` (seconds) | page unload / tab hidden | +5 if > 10s |
| `field_focus` | a credential-type field is focused | +5 |
| `typed_no_submit` | typing occurred but no submit | +10 |
| `submitted` | the form's submit event fires | +30 |

## Files

- **`beacon.js`** - the client beacon. Drop it on the simulation landing page.
- **`example_landing.html`** - a ready teaching page wired to the beacon, with
  a "this was a simulation" reveal on submit. It never posts the form.

## The privacy contract (read this)

The beacon and the server endpoint are built so that capturing a credential is
not merely *disallowed* but *impossible by construction*:

- `beacon.js` never reads any input's `.value`, and never inspects keystroke
  characters. "Typing happened" is a boolean; the content is never touched.
- The only number transmitted is elapsed seconds on the page.
- The server endpoint (`/api/v1/integrations/beacon/events`) accepts **only**
  the five event types above, rejects any event carrying a scalar other than
  `dwell` seconds, and rejects the whole batch if a field name looks like a
  credential (`password`, `otp`, `secret`, `token`, ...).

In GoPhish, set the landing page's **Capture Submitted Data -> OFF**. You never
want the data; the `submitted` *event* is the entire signal.

## Server configuration

Set a shared token so random traffic can't post events:

```
BEACON_INGEST_TOKEN=<long-random-string>
```

Embed the same value in `window.PHISH_BEACON.token`. The token is a spam-guard
embedded in a public page - treat it as such (rotate it per program, don't
reuse a real secret).

## Wiring per campaign

1. Create the campaign in the platform and note its `external_ref` - this must
   equal what you pass as `campaignRef`. Linking GoPhish's numeric campaign id
   via the GoPhish adapter (or **Manage -> Campaigns**) is the usual way.
2. In the landing page config set `endpoint`, `tenantId`, `token`, and let
   GoPhish template `{{.Email}}` / `{{.CampaignId}}`.
3. Run the campaign. Events flow in; hit **↻ Recompute** (or let the scheduled
   job run) to fold them into HRS.

Events for an email/campaign that isn't in the roster yet come back
`{"status":"unmapped"}` (accepted, not stored) so you can fix the link without
losing the run - same contract as the GoPhish webhook.
