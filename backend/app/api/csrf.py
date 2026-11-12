"""
CSRF protection for the cookie-based browser session (double-submit pattern).

Deliberately NOT a blanket middleware: verify_csrf() is called from
app/api/security.py's auth dependency only at the moment a request is about
to be authenticated via the session cookie on a state-changing method. A
route with no auth dependency at all (the public seed/webhook/beacon
endpoints) never triggers this check, no matter what cookies happen to be
present on the request - a middleware keyed on "cookie present" rather than
"cookie about to authenticate this request" would incorrectly reject those
routes too whenever a stale cookie from an earlier session happened to still
be attached (this is exactly what broke every test that seeds a tenant
after an earlier test in the same client session had already logged in).

A request carrying its own Authorization header (API/script clients, see
app/api/security.py's module docstring) is never subject to this check - a
malicious third-party page cannot forge a custom header on a cross-origin
request without a CORS grant, which is exactly the protection this exists
to provide for the cookie case, where the browser attaches the cookie
automatically regardless of origin.

No server-side token storage: the CSRF cookie is a random value set once at
login (set_auth_cookies) that JS can read (it is NOT httpOnly) and must
echo back as a header on any state-changing request. An attacker's page can
trigger the browser to *send* the cookie but cannot *read* it cross-origin,
so it can't reproduce the header value.
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

CSRF_HEADER_NAME = "x-csrf-token"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def verify_csrf(request: Request, csrf_cookie_name: str) -> None:
    """Raises 403 if this state-changing request's CSRF header doesn't match
    its CSRF cookie. Call only once you've decided the request IS being
    authenticated via the session cookie."""
    if request.method in SAFE_METHODS:
        return
    csrf_cookie = request.cookies.get(csrf_cookie_name)
    csrf_header = request.headers.get(CSRF_HEADER_NAME)
    if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or invalid CSRF token")
