"""
Portal middleware: security response headers + a small per-IP rate limit on the
auth endpoints (credential brute-force guard).
"""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

# The portal serves its own SPA (inline event handlers + inline styles), so the
# CSP must permit 'unsafe-inline'. We still lock frame-ancestors, object-src and
# base-uri, and allow https video embeds (admin-added training videos).
_CSP = ("default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "frame-src https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'self'")

_DOCS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy",
                     "geolocation=(), microphone=(), camera=()")
        if not request.url.path.startswith(_DOCS):
            h.setdefault("Content-Security-Policy", _CSP)
        if settings.is_production():
            h.setdefault("Strict-Transport-Security",
                         "max-age=63072000; includeSubDomains")
        return resp


_hits: dict[str, list[float]] = defaultdict(list)
_LIMITED = ("/api/portal/auth/login", "/api/portal/auth/register",
            "/api/portal/admin/auth/login")


def _reset() -> None:
    _hits.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        limit = settings.RATE_LIMIT_PER_MINUTE
        if limit and request.url.path in _LIMITED:
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            w = _hits[ip]
            w[:] = [t for t in w if t > now - 60.0]
            if len(w) >= limit:
                return JSONResponse(
                    {"detail": "rate limit exceeded - try again shortly"},
                    status_code=429)
            w.append(now)
        return await call_next(request)
