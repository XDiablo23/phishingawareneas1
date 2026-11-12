"""
Client for the PhishAwareness REST API (the /portal surface). Authenticates
with a per-tenant SERVICE TOKEN (header X-Portal-Token) instead of holding
a human operator/admin login - see routes_portal.py on the PhishAwareness
side for the matching require_portal_token dependency. This is the ONLY
channel between the two services for automation; login_verify() below is a
separate, unrelated concern (see its own docstring).
"""
from __future__ import annotations

import httpx

from app.config import settings
from app import models as m


class PAError(Exception):
    pass


class PAConn:
    def __init__(self, base_url, tenant_id, token, verify_tls=True):
        self.base_url = (base_url or "").rstrip("/")
        self.tenant_id = tenant_id or ""
        self.token = token or ""
        self.verify_tls = verify_tls

    @property
    def portal_base(self) -> str:
        return f"/api/v1/tenants/{self.tenant_id}/portal"


def _setting(db):
    return db.query(m.Setting).filter_by(id="singleton").first()


def resolve_conn(db) -> PAConn:
    """Effective PA connection: DB Setting overrides config.py boot values."""
    s = _setting(db)
    base = (s.pa_base_url if s and s.pa_base_url else settings.PA_BASE_URL)
    tid = (s.pa_tenant_id if s and s.pa_tenant_id else settings.PA_TENANT_ID)
    token = (s.pa_service_token if s and s.pa_service_token else settings.PA_SERVICE_TOKEN)
    return PAConn(base, tid, token, settings.PA_VERIFY_TLS)


def login_verify(base_url: str, email: str, password: str, verify_tls=True) -> dict:
    """Verify a human admin's PhishAwareness credentials (delegated login).
    This is unrelated to the service token above: it's a one-off check
    against PhishAwareness's own /auth/login, used only to authenticate an
    admin into the PORTAL's admin UI for their interactive session. Neither
    the password nor a resulting PhishAwareness token is ever persisted."""
    try:
        r = httpx.post(
            f"{base_url.rstrip('/')}/api/v1/auth/login",
            data={"username": email, "password": password},
            timeout=10.0, verify=verify_tls)
    except Exception as e:
        raise PAError(f"cannot reach PhishAwareness at {base_url}: {e}")
    if r.status_code != 200:
        raise PAError("incorrect email or password")
    return r.json()


def _req(conn: PAConn, method: str, path: str, **kw):
    if not (conn.token and conn.tenant_id):
        raise PAError("PhishAwareness connection is not configured "
                      "(missing service token or tenant id)")
    url = f"{conn.base_url}{path}"
    headers = kw.pop("headers", {})
    headers["X-Portal-Token"] = conn.token
    try:
        r = httpx.request(method, url, headers=headers,
                          timeout=15.0, verify=conn.verify_tls, **kw)
    except Exception as e:
        raise PAError(f"{method} {path}: {e}")
    if r.status_code >= 400:
        raise PAError(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


# --- typed helpers over the PhishAwareness /portal endpoints -------------
def list_signals(db) -> list[dict]:
    conn = resolve_conn(db)
    return _req(conn, "GET", f"{conn.portal_base}/employees")


def get_by_email(db, email: str) -> dict:
    conn = resolve_conn(db)
    return _req(conn, "GET", f"{conn.portal_base}/employees/by-email",
                params={"email": email})


def ensure_employee(db, email, full_name, department, job_title,
                    seniority_level=None) -> dict:
    conn = resolve_conn(db)
    return _req(conn, "POST", f"{conn.portal_base}/employees/ensure",
                json={"email": email, "full_name": full_name,
                      "department": department, "job_title": job_title,
                      "seniority_level": seniority_level})


def set_risk_floor(db, pa_employee_id: str, value) -> dict:
    conn = resolve_conn(db)
    return _req(conn, "POST",
                f"{conn.portal_base}/employees/{pa_employee_id}/risk-floor",
                json={"value": value})


def set_inperson_flag(db, pa_employee_id: str, on: bool, reason=None) -> dict:
    conn = resolve_conn(db)
    return _req(conn, "POST",
                f"{conn.portal_base}/employees/{pa_employee_id}/inperson-flag",
                json={"on": on, "reason": reason})


def test_connection(db) -> dict:
    conn = resolve_conn(db)
    out = {"base_url": conn.base_url, "tenant_id": conn.tenant_id,
           "token_set": bool(conn.token)}
    try:
        data = _req(conn, "GET", f"{conn.portal_base}/employees")
        out.update(ok=True, employees=len(data))
    except PAError as e:
        out.update(ok=False, error=str(e))
    return out
