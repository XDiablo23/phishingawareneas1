"""
Awareness & Remediation Portal - FastAPI entrypoint.

    uvicorn app.main:app --port 8100

A separate service from PhishAwareness with its own database. It serves the
employee + admin single-page app and talks to PhishAwareness only over REST.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.config import settings
from app.db import init_db, SessionLocal
from app.seed import ensure_seed
from app.crypto import ensure_secrets_encrypted
from app.routes_employee import router as employee_router
from app.routes_admin import router as admin_router
from app.middleware import SecurityHeadersMiddleware, RateLimitMiddleware

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


async def _auto_sync_loop() -> None:
    """Background escalation loop (enabled only when AUTO_SYNC_SECONDS > 0)."""
    from app import remediation as rem
    while True:
        await asyncio.sleep(max(30, settings.AUTO_SYNC_SECONDS))
        db = SessionLocal()
        try:
            rem.sync_all(db)
        except Exception:
            pass
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_seed(db)
        ensure_secrets_encrypted(db)
    finally:
        db.close()
    task = None
    if settings.AUTO_SYNC_SECONDS and settings.AUTO_SYNC_SECONDS > 0:
        task = asyncio.create_task(_auto_sync_loop())
    yield
    if task:
        task.cancel()


# Fail fast: never run in production on the built-in dev secret.
if settings.is_production() and settings.secret_is_default():
    raise RuntimeError(
        "PORTAL_SECRET_KEY is still the development default. Set a strong "
        "PORTAL_SECRET_KEY before running with PORTAL_ENV=production.")
if settings.is_production() and settings.encryption_key_is_default():
    raise RuntimeError(
        "PORTAL_ENCRYPTION_KEY is still the development default. Generate a "
        "real Fernet key before running with PORTAL_ENV=production.")

_docs = None if settings.is_production() else "/docs"
_redoc = None if settings.is_production() else "/redoc"
_openapi = None if settings.is_production() else "/openapi.json"
app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan,
              docs_url=_docs, redoc_url=_redoc, openapi_url=_openapi)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_list(),
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.APP_NAME,
            "version": settings.VERSION}


app.include_router(employee_router)
app.include_router(admin_router)

# Serve the single-page app last so the API routes above take precedence.
if os.path.isdir(_STATIC_DIR):
    @app.get("/")
    def _index():
        idx = os.path.join(_STATIC_DIR, "index.html")
        if os.path.isfile(idx):
            return FileResponse(idx)
        return JSONResponse({"detail": "SPA not built"}, status_code=404)

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="spa")
