"""SQLAlchemy engine/session for the portal's own database."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

_connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    settings.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=engine)
    _patch_schema()


def _patch_schema() -> None:
    """create_all() only creates TABLES that don't exist yet - it never adds
    a column to a table that's already on disk. This patches in columns
    added to the model after a table already existed (currently just
    Setting.pa_service_token, replacing the old pa_service_email/
    pa_service_password), so an existing portal.db doesn't need to be
    deleted when the schema grows. SQLite-only (its ALTER TABLE ADD COLUMN
    needs no batch/rebuild dance); a non-SQLite deployment needs a real
    migration tool, which is out of scope for this self-contained service."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(settings)")}
        if "pa_service_token" not in cols:
            conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN pa_service_token TEXT")

        # Scrub the credentials the token replaced. A portal.db created before
        # the service-token change still holds the operator's PhishAwareness
        # email and *plaintext password* in these columns - the automation
        # credential that used to be rewritten on every admin login. Nothing
        # reads them any more, and ensure_secrets_encrypted() only backfills
        # columns still in the model, so without this they would survive the
        # upgrade indefinitely. Blanking beats DROP COLUMN here: it works on
        # every SQLite version (DROP COLUMN only landed in 3.35) and doesn't
        # rewrite the table.
        # Written out literally rather than interpolated from a loop variable:
        # the statements are fixed, and a formatted SQL string here reads as an
        # injection sink to both a linter and a reviewer even when it isn't one.
        if "pa_service_email" in cols:
            conn.exec_driver_sql(
                "UPDATE settings SET pa_service_email = NULL "
                "WHERE pa_service_email IS NOT NULL")
        if "pa_service_password" in cols:
            conn.exec_driver_sql(
                "UPDATE settings SET pa_service_password = NULL "
                "WHERE pa_service_password IS NOT NULL")
