"""
Security response headers.

The backend serves a JSON API only (the console SPA is served separately), so
we can lock the Content-Security-Policy right down to `default-src 'none'`.
The interactive API docs (/docs, /redoc) load their assets from a CDN, so they
are exempted from the strict CSP in development - and disabled entirely in
production (see main.py). HSTS is emitted only in production, where the app is
assumed to sit behind TLS.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

# Paths whose responses must not get the strict `default-src 'none'` CSP,
# because they legitimately load scripts/styles (Swagger UI / ReDoc).
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy",
                     "geolocation=(), microphone=(), camera=(), interest-cohort=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        path = request.url.path
        if not any(path.startswith(p) for p in _CSP_EXEMPT_PREFIXES):
            h.setdefault("Content-Security-Policy",
                         "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            # API payloads can carry risk data; keep them out of shared caches.
            h.setdefault("Cache-Control", "no-store")
        if settings.is_production():
            h.setdefault("Strict-Transport-Security",
                         "max-age=63072000; includeSubDomains")
        return resp
