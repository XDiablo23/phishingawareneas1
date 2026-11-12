"""
On-prem Active Directory directory sync over LDAP.

Binds with a read-only service account and searches for users, then upserts
them into the roster (idempotent by email). Reads directory METADATA only
(name, mail, department, title, office) - never anyone's password. This is the
alternative to the Entra (Azure AD) path for organizations running on-prem AD.
"""
from __future__ import annotations

from app.config import settings
from app.db import models as m
from app.integrations.entra import _seniority  # shared title -> seniority rule
from app.integrations.directory_sync import upsert_roster_from_directory


class LdapError(Exception):
    pass


# AD attributes we read (metadata only).
_ATTRS = ["displayName", "mail", "userPrincipalName", "department", "title",
          "physicalDeliveryOfficeName", "sAMAccountName"]


def resolve_conn(tenant):
    """(uri, bind_dn, bind_password, base_dn, user_filter) - tenant overrides
    then env defaults."""
    uri = getattr(tenant, "ldap_uri", None) or settings.LDAP_URI or ""
    bind_dn = getattr(tenant, "ldap_bind_dn", None) or settings.LDAP_BIND_DN or ""
    bind_pw = getattr(tenant, "ldap_bind_password", None) or settings.LDAP_BIND_PASSWORD or ""
    base_dn = getattr(tenant, "ldap_base_dn", None) or settings.LDAP_BASE_DN or ""
    ufilter = getattr(tenant, "ldap_user_filter", None) or settings.LDAP_USER_FILTER
    return uri, bind_dn, bind_pw, base_dn, ufilter


def _entries(uri, bind_dn, bind_pw, base_dn, ufilter, limit=None):
    """Bind + paged search; returns a list of AD attribute dicts. Isolated so
    tests can patch it (no live domain controller needed). ldap3 is imported
    lazily so the module loads even before the dependency is installed."""
    import ldap3
    if not (uri and bind_dn and bind_pw and base_dn):
        raise LdapError("LDAP connection is not configured")
    use_ssl = uri.lower().startswith("ldaps://")
    try:
        server = ldap3.Server(uri, use_ssl=use_ssl, get_info=ldap3.NONE,
                              connect_timeout=10)
        conn = ldap3.Connection(server, user=bind_dn, password=bind_pw,
                                auto_bind=True)
    except Exception as e:
        raise LdapError(f"cannot bind to LDAP ({e})")
    out = []
    try:
        for entry in conn.extend.standard.paged_search(
                search_base=base_dn, search_filter=ufilter,
                attributes=_ATTRS, paged_size=200, generator=True):
            if entry.get("type") != "searchResEntry":
                continue
            a = entry.get("attributes", {}) or {}
            row = {}
            for k in _ATTRS:
                v = a.get(k)
                if isinstance(v, list):
                    v = v[0] if v else None
                row[k] = v
            out.append(row)
            if limit and len(out) >= limit:
                break
        return out
    except Exception as e:
        raise LdapError(f"LDAP search failed ({e})")
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


def fetch_users(tenant, limit=None):
    uri, bind_dn, bind_pw, base_dn, ufilter = resolve_conn(tenant)
    return _entries(uri, bind_dn, bind_pw, base_dn, ufilter, limit=limit)


def _map(e: dict) -> dict:
    email = (e.get("mail") or e.get("userPrincipalName") or "").strip().lower()
    return {
        "email": email,
        "full_name": e.get("displayName") or email,
        "department": e.get("department") or "Unassigned",
        "job_title": e.get("title") or "Employee",
        "office_location": e.get("physicalDeliveryOfficeName"),
        "seniority_level": _seniority(e.get("title")),
    }


def preview(tenant, limit=15):
    rows = [_map(e) for e in fetch_users(tenant, limit=limit)]
    return [r for r in rows if r["email"]]


def test_connection(tenant):
    uri, bind_dn, bind_pw, base_dn, ufilter = resolve_conn(tenant)
    out = {"configured": bool(uri and bind_dn and bind_pw and base_dn), "uri": uri}
    if not out["configured"]:
        out["ok"] = False
        out["error"] = "LDAP connection is not set"
        return out
    try:
        users = fetch_users(tenant, limit=1)
        out["ok"] = True
        out["sample_count"] = len(users)
    except LdapError as e:
        out["ok"] = False
        out["error"] = str(e)
    return out


def sync_users(db, tenant_id):
    """Import/refresh the roster from on-prem AD. Idempotent by email: creates
    new employees, updates existing ones' directory fields. Audit-logged."""
    tenant = db.query(m.Tenant).filter_by(id=tenant_id).first()
    if tenant is None:
        raise LdapError("tenant not found")
    users = fetch_users(tenant)
    return upsert_roster_from_directory(
        db, tenant_id, users, _map, "ldap-sync", "sync_ldap")
