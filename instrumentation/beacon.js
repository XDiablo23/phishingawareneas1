/*
 * Phishing-Awareness Landing Beacon
 * ---------------------------------
 * Drops onto a SIMULATION landing page (hosted by GoPhish, run by your own
 * security team, against your own consenting employees) and reports the rich
 * interaction signals GoPhish cannot see on its own: dwell time, credential-
 * field focus, and typing-without-submitting. Those feed the compromise-depth
 * ladder in the scoring platform.
 *
 * PRIVACY - non-negotiable, and enforced by what this file does NOT do:
 *   - It never reads an input's .value. Not once. There is no code path here
 *     that can obtain what a person typed.
 *   - It attaches no character-level key logging. "Typing happened" is a single
 *     boolean; the characters are never inspected or transmitted.
 *   - The only number it ever sends is elapsed seconds on the page.
 *   - It transmits: event type + (for dwell) seconds. Nothing else.
 *
 * If you ever find yourself tempted to send field contents "just for realism",
 * stop: that turns an awareness tool into a credential harvester, the backend
 * will reject it, and it is exactly what this project refuses to build.
 *
 * ---- Integration -------------------------------------------------------
 * Configure BEFORE loading this script:
 *
 *   <script>
 *     window.PHISH_BEACON = {
 *       endpoint:   "https://scoring.example.org/api/v1/integrations/beacon/events",
 *       tenantId:   "<tenant-uuid>",
 *       token:      "<BEACON_INGEST_TOKEN>",      // matches server config
 *       campaignRef:"{{.CampaignId}}",            // GoPhish template var
 *       email:      "{{.Email}}"                  // GoPhish template var
 *     };
 *   </script>
 *   <script src="beacon.js" defer></script>
 *
 * GoPhish substitutes {{.Email}} / {{.CampaignId}} per recipient at send time.
 * `campaignRef` must equal the campaign's `external_ref` in the platform
 * (link it once via the GoPhish adapter / Manage -> Campaigns).
 */
(function () {
  "use strict";

  var cfg = window.PHISH_BEACON || {};
  if (!cfg.endpoint || !cfg.tenantId || !cfg.campaignRef || !cfg.email) {
    // Misconfigured: stay silent rather than spraying errors on a live page.
    return;
  }

  var start = Date.now();
  var typed = false;          // did ANY typing occur? (content never inspected)
  var focusedField = false;   // did a credential-ish field get focus?
  var submitted = false;
  var sentClick = false;

  function secondsOnPage() {
    return Math.round((Date.now() - start) / 1000);
  }

  // Fire-and-forget. sendBeacon survives page unload; fetch is the fallback.
  function emit(events) {
    var payload = JSON.stringify({
      token: cfg.token || null,
      campaign_ref: String(cfg.campaignRef),
      email: String(cfg.email),
      events: events
    });
    var url = cfg.endpoint + "?tenant_id=" + encodeURIComponent(cfg.tenantId);
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(url, new Blob([payload], { type: "application/json" }));
        return;
      }
    } catch (e) { /* fall through to fetch */ }
    try {
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
        mode: "cors"
      });
    } catch (e) { /* nothing we can do; never block the page */ }
  }

  // Landing on the page IS the click-through from the email.
  function emitClickOnce() {
    if (sentClick) return;
    sentClick = true;
    emit([{ type: "clicked" }]);
  }

  // Is this input a credential-type field? Decided from the element's TYPE and
  // NAME only - we look at metadata about the field, never its contents.
  function looksLikeCredentialField(el) {
    if (!el || el.tagName !== "INPUT") return false;
    var t = (el.type || "").toLowerCase();
    if (t === "password") return true;
    var hint = ((el.name || "") + " " + (el.id || "") + " " +
                (el.autocomplete || "")).toLowerCase();
    return /pass|pwd|otp|secret|user|email|login|account/.test(hint);
  }

  document.addEventListener("focusin", function (e) {
    if (!focusedField && looksLikeCredentialField(e.target)) {
      focusedField = true;
      emit([{ type: "field_focus" }]);
    }
  });

  // "input" tells us typing happened. We read e.type, never e.target.value.
  document.addEventListener("input", function (e) {
    if (e.target && e.target.tagName === "INPUT") {
      typed = true;
    }
  });

  document.addEventListener("submit", function () {
    submitted = true;
    // The submit event alone is the signal; we do not read the form fields.
    flush(true);
  });

  // Send dwell (+ typed_no_submit if applicable) when the visit ends.
  function flush(fromSubmit) {
    var events = [{ type: "dwell", seconds: secondsOnPage() }];
    if (fromSubmit && submitted) {
      events.push({ type: "submitted" });
    } else if (typed && !submitted) {
      events.push({ type: "typed_no_submit" });
    }
    emit(events);
  }

  // Page-load: record the click-through immediately so it lands even on a
  // bounce; dwell/typed are reconciled at unload.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", emitClickOnce);
  } else {
    emitClickOnce();
  }

  var flushed = false;
  function finalFlush() {
    if (flushed) return;
    flushed = true;
    flush(false);
  }
  // visibilitychange(hidden) is the most reliable "leaving" signal on mobile.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") finalFlush();
  });
  window.addEventListener("pagehide", finalFlush);
})();
