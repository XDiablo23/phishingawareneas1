"""
Lightweight per-IP rate limiting for sensitive endpoints (auth + public
ingestion). Fixed 60-second window, in-memory. Dependency-free and disabled
by default (RATE_LIMIT_PER_MINUTE = 0) so local/dev/test are unaffected; set
the env var in production. For multi-node deployments swap the in-memory
store for Redis - the middleware boundary stays the same.
"""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

# Only auth and the public ingestion endpoints are limited; the authenticated
# dashboard/manage API is protected by JWT + RBAC and used interactively.
LIMITED_PREFIXES = ("/api/v1/auth/login", "/api/v1/integrations/")

_hits: dict[str, list[float]] = defaultdict(list)


def _reset() -> None:
    """Clear the in-memory counters (used by tests)."""
    _hits.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        limit = settings.RATE_LIMIT_PER_MINUTE
        if limit and any(request.url.path.startswith(p) for p in LIMITED_PREFIXES):
            ip = request.client.host if request.client else "unknown"
            now = time.time()
            window = _hits[ip]
            cutoff = now - 60.0
            window[:] = [t for t in window if t > cutoff]
            if len(window) >= limit:
                return JSONResponse(
                    {"detail": "rate limit exceeded - try again shortly"},
                    status_code=429,
                )
            window.append(now)
        return await call_next(request)
