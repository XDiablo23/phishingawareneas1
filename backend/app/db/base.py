"""SQLAlchemy engine, session factory, and declarative base.

Works against Postgres (production, via Docker) and SQLite (tests/local).
We avoid Postgres-only column types so the same models run on both.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. In production, prefer Alembic migrations; this is
    used for the SQLite dev/test path and first-run bootstrap."""
    from app.db import models  # noqa: F401  (ensure models are imported)
    Base.metadata.create_all(bind=engine)
