"""
Authentication & authorization for the dashboard API.

This is the *platform's own* admin auth - hashed operator logins for the
console. It has nothing to do with phishing credential capture; no target
credential is ever involved.

Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib, no native deps).
Sessions are stateless JWTs (HS256).

Two auth surfaces are supported side by side:
  * Browser (the React console): an httpOnly Secure session cookie, so the
    token itself is never reachable from JS (an XSS payload can't read or
    exfiltrate it) - see set_auth_cookies()/clear_auth_cookies(). A separate,
    JS-readable CSRF cookie (double-submit pattern, checked in
    app/api/csrf.py) guards state-changing requests made this way.
  * API / script clients (curl, the documented integration examples in
    docs/GoPhish_Integration.md): the classic `Authorization: Bearer <jwt>`
    header, still returned in the login JSON body. A request that sends its
    own Authorization header is never subject to CSRF checks - a malicious
    page cannot forge one cross-origin without a CORS grant, which is the
    protection cookie-based CSRF exists to provide in the first place.
get_current_user() below accepts either source, header taking precedence.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from base64 import urlsafe_b64encode, urlsafe_b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import get_db
from app.db import models as m
from app.api.csrf import verify_csrf

_PBKDF2_ROUNDS = 200_000
_ALGO = "HS256"
_TOKEN_TTL_HOURS = 12

ACCESS_COOKIE_NAME = "access_token"
CSRF_COOKIE_NAME = "csrf_token"
_COOKIE_MAX_AGE = _TOKEN_TTL_HOURS * 3600

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# --- password hashing ----------------------------------------------------
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2${_PBKDF2_ROUNDS}${urlsafe_b64encode(salt).decode()}${urlsafe_b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_b64, dk_b64 = stored.split("$")
        assert scheme == "pbkdf2"
        salt = urlsafe_b64decode(salt_b64)
        expected = urlsafe_b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def generate_temp_password(nbytes: int = 9) -> str:
    """A readable one-time password for newly provisioned / reset accounts."""
    import secrets
    return secrets.token_urlsafe(nbytes)


# --- tokens --------------------------------------------------------------
def create_access_token(user: "m.User") -> str:
    payload = {
        "sub": user.id,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "tenant_id": user.tenant_id,
        "dept": user.department_scope,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGO)


def _decode(token: str) -> dict:
    # Pin the algorithm and require an expiry so a token with no/stale exp,
    # or one forged under a different alg, is rejected.
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGO],
                      options={"require": ["exp"]})


# --- cookie session (browser) ---------------------------------------------
def set_auth_cookies(response: Response, token: str) -> None:
    """Set the httpOnly session cookie plus its JS-readable CSRF companion
    (double-submit pattern - see app/api/csrf.py). Called on login.

    SameSite=Lax cookies are never attached to a cross-site fetch/XHR at all
    (only to top-level navigation), so a console served from a different
    origin than the API (VITE_API_BASE - see CORS_ORIGINS/allow_credentials
    in main.py) would silently 401 on every request post-login despite the
    CORS grant. In production (Secure is required for SameSite=None anyway,
    and production already terminates TLS) we use None so that documented
    split-origin deployment actually works; local dev stays same-origin via
    the Vite proxy, where Lax is correct and doesn't need HTTPS. This is safe
    because CSRF is enforced explicitly (verify_csrf), not relied upon via
    SameSite - dropping to None here doesn't remove any real protection."""
    secure = settings.is_production()
    samesite = "none" if secure else "lax"
    response.set_cookie(
        ACCESS_COOKIE_NAME, token, max_age=_COOKIE_MAX_AGE, httponly=True,
        secure=secure, samesite=samesite, path="/")
    response.set_cookie(
        CSRF_COOKIE_NAME, secrets.token_urlsafe(32), max_age=_COOKIE_MAX_AGE,
        httponly=False, secure=secure, samesite=samesite, path="/")


def clear_auth_cookies(response: Response) -> None:
    """Called on logout. Only a server round-trip can clear an httpOnly
    cookie - JS cannot delete it itself, which is the point of httpOnly."""
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


# --- dependencies --------------------------------------------------------
class CurrentUser:
    def __init__(self, claims: dict):
        self.id = claims.get("sub")
        self.email = claims.get("email")
        self.role = claims.get("role")
        self.tenant_id = claims.get("tenant_id")
        self.department_scope = claims.get("dept")

    @property
    def is_super_admin(self) -> bool:
        return self.role == "super_admin"


def _extract_token(
    request: Request, header_token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[str]:
    """Authorization header takes precedence (explicit API/script intent);
    otherwise fall back to the session cookie (browser console). CSRF is
    checked here, not as a blanket middleware, so it only ever applies to a
    request that is actually about to be authenticated via the cookie -
    routes with no auth dependency (seed/webhook/beacon) are never affected
    by a stray cookie."""
    if header_token:
        return header_token
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME)
    if cookie_token:
        verify_csrf(request, CSRF_COOKIE_NAME)
    return cookie_token


def get_current_user(token: Optional[str] = Depends(_extract_token)) -> CurrentUser:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    try:
        claims = _decode(token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return CurrentUser(claims)


def require_roles(*roles: str):
    """Dependency factory: allow only the given roles (super_admin always ok)."""
    allowed = set(roles) | {"super_admin"}

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"role '{user.role}' not permitted here")
        return user

    return _dep


def enforce_tenant(user: CurrentUser, tenant_id: str):
    """A non-super-admin may only touch their own tenant."""
    if user.is_super_admin:
        return
    if user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "not permitted for this tenant")


def dept_filter_for(user: CurrentUser) -> Optional[str]:
    """A departmental viewer is scoped to their own department; others see all."""
    if user.role == "dept_viewer":
        return user.department_scope
    return None
