"""Production-hardening tests: CORS lockdown, SECRET_KEY guard, rate limiting."""
import os
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.db.base as base
base.engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False},
    poolclass=StaticPool, future=True)
base.SessionLocal.configure(bind=base.engine)

from app.main import app  # noqa: E402
from app.db.base import init_db  # noqa: E402
from app.config import settings  # noqa: E402
from app.api import ratelimit  # noqa: E402


@pytest.fixture(scope="module")
def client():
    init_db()
    return TestClient(app)


def test_cors_not_wildcard():
    origins = settings.cors_origins_list()
    assert "*" not in origins
    assert "http://localhost:5173" in origins


def test_secret_guard_helpers():
    # production + default secret must be flagged (main.py fails fast on this)
    assert settings.secret_is_default() is True  # dev default in the test env
    assert isinstance(settings.is_production(), bool)


def test_cors_allows_configured_origin(client):
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_blocks_unlisted_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("access-control-allow-origin") is None


def test_rate_limit_returns_429(client, monkeypatch):
    ratelimit._reset()
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 3)
    try:
        codes = [client.post("/api/v1/auth/login",
                             data={"username": "x@y.z", "password": "nope"}).status_code
                 for _ in range(5)]
        assert codes[0] != 429          # first requests get through
        assert codes.count(429) >= 1    # later ones are throttled
    finally:
        ratelimit._reset()
        monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 0)


def test_rate_limit_disabled_by_default(client):
    ratelimit._reset()
    codes = [client.post("/api/v1/auth/login",
                         data={"username": "x@y.z", "password": "nope"}).status_code
             for _ in range(8)]
    assert 429 not in codes  # disabled (limit 0) -> never throttles
