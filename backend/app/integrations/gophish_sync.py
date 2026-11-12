"""
GoPhish sync - pull campaigns/results from the GoPhish REST API into our
platform so an org runs everything from one front-facing console.

READ-ONLY by design: we only GET campaigns/results/timeline. We never create,
launch, or send a campaign from here - that stays an explicit action in GoPhish.
Submitted-form payloads in the timeline are ignored; only the fact of an event
is recorded (credentials are never stored), exactly like the webhook adapter.
"""
from __future__ import annotations

import json
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone

from app.config import settings
from app.db import models as m

# GoPhish timeline/webhook message -> our EventType value
_EVENT_MAP = {
    "Email Opened": "opened",
    "Clicked Link": "clicked",
    "Submitted Data": "submitted",
    "Email Reported": "reported",
}


class GoPhishError(Exception):
    pass


def resolve_conn(tenant):
    """(base_url, api_key, verify_tls) - per-tenant overrides then env defaults.

    verify_tls in particular must resolve per-tenant, not just base_url/
    api_key: each tenant points at its own GoPhish server, so one tenant's
    server having a self-signed cert (verify off) must not force every other
    tenant sharing this deployment to also skip verification."""
    base = (getattr(tenant, "gophish_base_url", None) or settings.GOPHISH_API_URL or "").rstrip("/")
    key = getattr(tenant, "gophish_api_key", None) or settings.GOPHISH_API_KEY or ""
    tenant_verify = getattr(tenant, "gophish_verify_tls", None)
    verify = tenant_verify if tenant_verify is not None else settings.GOPHISH_VERIFY_TLS
    return base, key, verify


def _ctx(verify):
    if verify:
        return None
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _get(base, key, path, verify):
    if not base or not key:
        raise GoPhishError("GoPhish base URL or API key not configured")
    req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ctx(verify)) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise GoPhishError(f"GoPhish API error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise GoPhishError(f"cannot reach GoPhish ({e.reason})")
    except (ValueError, TimeoutError) as e:
        raise GoPhishError(str(e))


def list_campaigns(tenant):
    base, key, verify = resolve_conn(tenant)
    return _get(base, key, "/api/campaigns/", verify)


def test_connection(tenant):
    base, key, verify = resolve_conn(tenant)
    out = {"configured": bool(base and key), "base_url": base,
           "reachable": False, "campaign_count": 0, "error": None}
    if not out["configured"]:
        out["error"] = "GoPhish API key not set"
        return out
    try:
        camps = list_campaigns(tenant)
        out["reachable"] = True
        out["campaign_count"] = len(camps) if isinstance(camps, list) else 0
    except GoPhishError as e:
        out["error"] = str(e)
    return out


def _parse_time(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else datetime.now(timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _stats(gc):
    c = {"sent": 0, "opened": 0, "clicked": 0, "submitted": 0, "reported": 0}
    for ev in gc.get("timeline", []) or []:
        msg = ev.get("message")
        if msg == "Email Sent":
            c["sent"] += 1
        elif msg in _EVENT_MAP:
            c[_EVENT_MAP[msg]] += 1
    return c


def list_campaigns_view(tenant):
    """Lightweight campaign list for the console: id, name, status, stats,
    and whether it's already linked to a platform campaign."""
    from app.db.base import SessionLocal
    camps = list_campaigns(tenant)
    view = []
    s = SessionLocal()
    try:
        for gc in (camps if isinstance(camps, list) else []):
            ext = str(gc.get("id"))
            linked = s.query(m.Campaign).filter_by(
                tenant_id=tenant.id, external_ref=ext).first() is not None
            view.append({"id": gc.get("id"), "name": gc.get("name"),
                         "status": gc.get("status"), "launch_date": gc.get("launch_date"),
                         "stats": _stats(gc), "linked": linked})
    finally:
        s.close()
    return view


def sync_tenant(db, tenant_id):
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise GoPhishError("tenant not found")
    campaigns = list_campaigns(tenant)
    if not isinstance(campaigns, list):
        raise GoPhishError("unexpected GoPhish response")

    out = {"campaigns_synced": 0, "employees_created": 0,
           "events_ingested": 0, "skipped_existing": 0, "details": []}

    for gc in campaigns:
        ext = str(gc.get("id"))
        camp = db.query(m.Campaign).filter_by(tenant_id=tenant_id, external_ref=ext).first()
        if camp is None:
            # New link: default tier/vector; the operator can refine in Manage.
            camp = m.Campaign(tenant_id=tenant_id, name=gc.get("name") or f"GoPhish {ext}",
                              tier=2, attack_vector=m.AttackVector.credential_harvest,
                              status=m.CampaignStatus.running, external_ref=ext)
            db.add(camp)
            db.flush()

        names = {}
        for res in gc.get("results", []) or []:
            em = (res.get("email") or "").strip().lower()
            if em:
                names[em] = res

        ingested = 0
        for ev in gc.get("timeline", []) or []:
            et = _EVENT_MAP.get(ev.get("message"))
            if et is None:
                continue
            em = (ev.get("email") or "").strip().lower()
            if not em:
                continue
            emp = db.query(m.Employee).filter_by(tenant_id=tenant_id, email=em).first()
            if emp is None:
                r = names.get(em, {})
                fn = ((r.get("first_name") or "") + " " + (r.get("last_name") or "")).strip() or em
                emp = m.Employee(tenant_id=tenant_id, full_name=fn, email=em,
                                 department=r.get("department") or "Imported",
                                 job_title=r.get("position") or "Unknown")
                db.add(emp)
                db.flush()
                out["employees_created"] += 1
            occurred = _parse_time(ev.get("time"))
            dup = db.query(m.InteractionEvent).filter_by(
                tenant_id=tenant_id, campaign_id=camp.id, employee_id=emp.id,
                event_type=m.EventType(et), occurred_at=occurred).first()
            if dup:
                out["skipped_existing"] += 1
                continue
            # metadata only - provenance, never the submitted form payload
            db.add(m.InteractionEvent(
                tenant_id=tenant_id, campaign_id=camp.id, employee_id=emp.id,
                event_type=m.EventType(et), value=None, breached=None,
                occurred_at=occurred,
                event_metadata={"source": "gophish", "ingest": "sync",
                                "gophish_campaign": ext, "gophish_event": ev.get("message")}))
            ingested += 1
        out["events_ingested"] += ingested
        out["campaigns_synced"] += 1
        out["details"].append({"gophish_id": ext, "name": gc.get("name"),
                               "events_ingested": ingested, "stats": _stats(gc)})

    db.add(m.AuditLog(tenant_id=tenant_id, actor="gophish-sync", action="sync_gophish",
                      detail={"campaigns": out["campaigns_synced"],
                              "events": out["events_ingested"]}))
    db.commit()
    return out
