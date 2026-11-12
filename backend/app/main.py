"""
FastAPI application entrypoint.

    uvicorn app.main:app --reload

This is the measurement-layer API: it ingests interaction-event metadata
and serves risk analytics. It does not generate lures, clone pages,
capture credentials, or send anything.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.api.ratelimit import RateLimitMiddleware
from app.api.security_headers import SecurityHeadersMiddleware
from app.api.routes import router as api_router
from app.api.routes_auth import router as auth_router
from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_manage import router as manage_router
from app.api.routes_portal import router as portal_router
from app.integrations.gophish_webhook import router as gophish_router
from app.integrations.beacon import router as beacon_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Bootstrap tables (idempotent). Works for both SQLite and Postgres so
    # `docker compose up` runs with no manual migration step. Set
    # USE_ALEMBIC=1 to manage the schema with Alembic migrations instead.
    if not settings.USE_ALEMBIC:
        from app.db.base import init_db
        init_db()
    yield


# Fail fast: never run in production on the built-in dev secret.
if settings.is_production() and settings.secret_is_default():
    raise RuntimeError(
        "SECRET_KEY is still the development default. Set a strong SECRET_KEY "
        "before running with ENV=production."
    )
if settings.is_production() and settings.encryption_key_is_default():
    raise RuntimeError(
        "ENCRYPTION_KEY is still the development default. Generate a real "
        "Fernet key before running with ENV=production (see .env.example)."
    )

# Interactive API docs are handy in dev but expose the full schema; disable
# them in production.
_docs = None if settings.is_production() else "/docs"
_redoc = None if settings.is_production() else "/redoc"
_openapi = None if settings.is_production() else "/openapi.json"
app = FastAPI(title=settings.APP_NAME, version="0.7.0", lifespan=lifespan,
              docs_url=_docs, redoc_url=_redoc, openapi_url=_openapi)

# Security response headers (nosniff, frame-deny, strict CSP on the API, HSTS
# in production). Added first so it wraps everything below.
app.add_middleware(SecurityHeadersMiddleware)

# CORS locked to configured origins (never '*' in production - the console
# now relies on a cookie, and allow_credentials forbids a wildcard origin
# anyway). Defaults to local dev origins; override with CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Per-IP rate limiting on auth + ingestion (no-op unless RATE_LIMIT_PER_MINUTE > 0).
app.add_middleware(RateLimitMiddleware)

# CSRF protection (double-submit pattern) is NOT a blanket middleware here -
# see app/api/csrf.py's module docstring for why it's checked instead from
# inside the auth dependency, only when a request is actually about to be
# authenticated via the session cookie.


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.APP_NAME, "version": app.version}


app.include_router(auth_router)
app.include_router(api_router)
app.include_router(dashboard_router)
app.include_router(manage_router)
app.include_router(portal_router)
app.include_router(gophish_router)
app.include_router(beacon_router)
