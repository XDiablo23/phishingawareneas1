"""
GoPhish admin / write operations - the operator control surface that lets the
org run the full campaign lifecycle from our console.

Scope, deliberately: we ORCHESTRATE GoPhish's own REST API - build target
groups from our roster, and create / launch / schedule / complete / delete
campaigns that reference an email template, a landing page and a sending
profile the operator authored **inside GoPhish**. We do NOT author or clone
lure emails or landing pages here, and we never read or store credentials.
Every write is authorization-gated and audit-logged at the API layer.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.integrations.gophish_sync import resolve_conn, GoPhishError, _ctx


def _request(base, key, method, path, body=None, verify=True):
    if not base or not key:
        raise GoPhishError("GoPhish base URL or API key not configured")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=_ctx(verify)) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        raise GoPhishError(f"GoPhish API error {e.code}: {detail or e.reason}")
    except urllib.error.URLError as e:
        raise GoPhishError(f"cannot reach GoPhish ({e.reason})")
    except (ValueError, TimeoutError) as e:
        raise GoPhishError(str(e))


# --- pickers (read-only): content the operator authored in GoPhish --------
def list_templates(tenant):
    base, key, v = resolve_conn(tenant)
    rows = _request(base, key, "GET", "/api/templates/", None, v) or []
    return [{"id": t.get("id"), "name": t.get("name")} for t in rows]


def list_pages(tenant):
    base, key, v = resolve_conn(tenant)
    rows = _request(base, key, "GET", "/api/pages/", None, v) or []
    # surface capture flags so the console can WARN (and default to off)
    return [{"id": p.get("id"), "name": p.get("name"),
             "capture_credentials": bool(p.get("capture_credentials")),
             "capture_passwords": bool(p.get("capture_passwords"))}
            for p in rows]


def list_smtp(tenant):
    base, key, v = resolve_conn(tenant)
    rows = _request(base, key, "GET", "/api/smtp/", None, v) or []
    return [{"id": s.get("id"), "name": s.get("name"),
             "from_address": s.get("from_address")} for s in rows]


def list_groups(tenant):
    base, key, v = resolve_conn(tenant)
    rows = _request(base, key, "GET", "/api/groups/", None, v) or []
    return [{"id": g.get("id"), "name": g.get("name"),
             "targets": len(g.get("targets") or [])} for g in rows]


# --- target groups from OUR roster (write) --------------------------------
def _split_name(full):
    parts = (full or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def push_group_from_roster(tenant, name, employees):
    """Create or update a GoPhish group whose targets ARE our roster (subset).
    Idempotent by group name."""
    targets = []
    for e in employees:
        fn, ln = _split_name(e.full_name)
        targets.append({"first_name": fn, "last_name": ln,
                        "email": e.email, "position": e.job_title or ""})
    base, key, v = resolve_conn(tenant)
    existing = None
    for g in (_request(base, key, "GET", "/api/groups/", None, v) or []):
        if g.get("name") == name:
            existing = g
            break
    payload = {"name": name, "targets": targets}
    if existing:
        payload["id"] = existing["id"]
        res = _request(base, key, "PUT", f"/api/groups/{existing['id']}", payload, v)
    else:
        res = _request(base, key, "POST", "/api/groups/", payload, v)
    return {"id": res.get("id"), "name": res.get("name"), "targets": len(targets)}


# --- campaigns (write): create/launch/schedule/complete/delete ------------
def create_campaign(tenant, spec: dict):
    """Create (and thereby launch or schedule) a campaign in GoPhish that
    references existing content by name. `spec` keys: name, template, page,
    smtp, group, url, launch_date?, send_by_date?. GoPhish launches on create
    (or at launch_date if it is in the future)."""
    base, key, v = resolve_conn(tenant)
    body = {
        "name": spec["name"],
        "template": {"name": spec["template"]},
        "page": {"name": spec["page"]},
        "smtp": {"name": spec["smtp"]},
        "url": spec["url"],
        "groups": [{"name": spec["group"]}],
    }
    if spec.get("launch_date"):
        body["launch_date"] = spec["launch_date"]
    if spec.get("send_by_date"):
        body["send_by_date"] = spec["send_by_date"]
    return _request(base, key, "POST", "/api/campaigns/", body, v)


def complete_campaign(tenant, campaign_id):
    base, key, v = resolve_conn(tenant)
    return _request(base, key, "GET", f"/api/campaigns/{campaign_id}/complete", None, v)


def delete_campaign(tenant, campaign_id):
    base, key, v = resolve_conn(tenant)
    return _request(base, key, "DELETE", f"/api/campaigns/{campaign_id}", None, v)
