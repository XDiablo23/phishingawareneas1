"""
Microsoft Entra ID (Azure AD) directory sync.

Client-credentials OAuth2 against Microsoft Graph, then read directory users
into the employee roster. This reads directory **metadata only**
(display name, mail, department, job title, office) - it never reads or stores
any user's credentials, and it only ever creates/updates employee records.

Requires an Entra app registration with an application permission such as
User.Read.All or Directory.Read.All (admin-consented).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings
from app.db import models as m
from app.integrations.directory_sync import upsert_roster_from_directory

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
_SELECT = "id,displayName,mail,userPrincipalName,department,jobTitle,officeLocation,accountEnabled"

# Hosts this module is ever allowed to talk to. fetch_users() paginates by
# following a `@odata.nextLink` URL taken from Graph's own response body,
# not one we constructed - validating scheme+host here (for every outbound
# call, not just pagination) means a malformed or compromised response can
# never redirect this integration to an arbitrary host/scheme.
_ALLOWED_HOSTS = {"graph.microsoft.com", "login.microsoftonline.com"}


class EntraError(Exception):
    pass


def _ensure_allowed_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise EntraError(
            f"refusing to follow untrusted URL for Microsoft Entra sync: {parsed.hostname!r}")


def resolve_conn(tenant):
    """(tenant_id, client_id, client_secret) - per-tenant overrides then env."""
    tid = getattr(tenant, "entra_tenant_id", None) or settings.ENTRA_TENANT_ID or ""
    cid = getattr(tenant, "entra_client_id", None) or settings.ENTRA_CLIENT_ID or ""
    sec = getattr(tenant, "entra_client_secret", None) or settings.ENTRA_CLIENT_SECRET or ""
    return tid, cid, sec


def _http(req: urllib.request.Request, what: str):
    _ensure_allowed_url(req.full_url)
    try:
        # Scheme/host validated by _ensure_allowed_url() immediately above -
        # only https://graph.microsoft.com and https://login.microsoftonline.com
        # can ever reach this call.
        with urllib.request.urlopen(req, timeout=25) as r:  # nosec B310
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        raise EntraError(f"{what} error {e.code}: {detail or e.reason}")
    except urllib.error.URLError as e:
        raise EntraError(f"cannot reach {what} ({e.reason})")
    except (ValueError, TimeoutError) as e:
        raise EntraError(str(e))


def _token(tid, cid, sec):
    if not (tid and cid and sec):
        raise EntraError("Azure AD connection is not configured")
    data = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(
        f"{LOGIN}/{tid}/oauth2/v2.0/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return _http(req, "Microsoft login")["access_token"]


def fetch_users(tenant, limit=None):
    tid, cid, sec = resolve_conn(tenant)
    token = _token(tid, cid, sec)
    url = f"{GRAPH}/users?$select={_SELECT}&$top=100"
    out = []
    while url:
        page = _http(urllib.request.Request(
            url, headers={"Authorization": "Bearer " + token}), "Microsoft Graph")
        for u in page.get("value", []):
            out.append(u)
            if limit and len(out) >= limit:
                return out
        url = page.get("@odata.nextLink")
    return out


def _seniority(title: str) -> str:
    # Match short abbreviations (ceo, cto, vp, ...) as WHOLE words, so a title
    # like "Director" isn't misread as Exec because it contains "cto".
    t = (title or "").lower()
    words = set(re.findall(r"[a-z]+", t))
    if ("chief" in t or "president" in t or "founder" in t
            or words & {"ceo", "cfo", "cto", "ciso", "cio", "coo", "cmo", "cpo", "vp"}):
        return "Exec"
    if "director" in t or "head of" in t:
        return "Director"
    if any(k in t for k in ("manager", "lead", "supervisor", "principal", "head,")):
        return "Manager"
    return "Staff"


def _map(u: dict) -> dict:
    email = (u.get("mail") or u.get("userPrincipalName") or "").strip().lower()
    return {
        "email": email,
        "full_name": u.get("displayName") or email,
        "department": u.get("department") or "Unassigned",
        "job_title": u.get("jobTitle") or "Employee",
        "office_location": u.get("officeLocation"),
        "seniority_level": _seniority(u.get("jobTitle")),
    }


def preview(tenant, limit=15):
    """A sample of mapped users (no writes) so an admin can sanity-check the
    connection and field mapping before importing."""
    rows = [_map(u) for u in fetch_users(tenant, limit=limit)]
    return [r for r in rows if r["email"]]


def test_connection(tenant):
    tid, cid, sec = resolve_conn(tenant)
    out = {"configured": bool(tid and cid and sec), "tenant_id": tid}
    if not out["configured"]:
        out["ok"] = False
        out["error"] = "Azure AD connection is not set"
        return out
    try:
        users = fetch_users(tenant, limit=1)
        out["ok"] = True
        out["sample_count"] = len(users)
    except EntraError as e:
        out["ok"] = False
        out["error"] = str(e)
    return out


def sync_users(db, tenant_id):
    """Import/refresh the roster from Entra. Idempotent by email: creates new
    employees, updates existing ones' directory fields. Audit-logged."""
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise EntraError("tenant not found")
    users = fetch_users(tenant)
    return upsert_roster_from_directory(
        db, tenant_id, users, _map, "entra-sync", "sync_entra")
