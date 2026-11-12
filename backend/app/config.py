"""Application configuration (env-driven, with local defaults)."""

from __future__ import annotations

import os
from pathlib import Path

# Load backend/.env if present; real env vars (Docker/CI) take precedence.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover - dotenv is in requirements
    pass


class Settings:
    # SQLite by default; docker-compose.yml overrides with the Postgres URL.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./phishawareness.db",
    )
    # JWT / dashboard auth key. Never a hardcoded secret in prod.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-change-me")
    # Encrypts secret columns at rest (webhook_secret, ingest_token,
    # gophish_api_key, entra_client_secret, ldap_bind_password) - a Fernet
    # key, i.e. 32 url-safe base64 bytes. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Never the dev default in production (see encryption_key_is_default()).
    ENCRYPTION_KEY: str = os.getenv(
        "ENCRYPTION_KEY", "FXPBSe4qk56uo9FnmzrI6wqXj4YjnEdOKHeJiipZqiM=")
    # HMAC secret for the GoPhish webhook. Empty = signatures not verified (dev).
    GOPHISH_WEBHOOK_SECRET: str = os.getenv("GOPHISH_WEBHOOK_SECRET", "")
    # Spam-guard token for the public beacon endpoint. Empty = accept unsigned (dev).
    BEACON_INGEST_TOKEN: str = os.getenv("BEACON_INGEST_TOKEN", "")
    # GoPhish REST API for the read-only results sync (per-tenant overridable in Manage).
    GOPHISH_API_URL: str = os.getenv("GOPHISH_API_URL", "https://127.0.0.1:3333")
    GOPHISH_API_KEY: str = os.getenv("GOPHISH_API_KEY", "")
    # GoPhish uses a self-signed cert; default off. Set true with a real cert.
    GOPHISH_VERIFY_TLS: bool = os.getenv("GOPHISH_VERIFY_TLS", "").lower() in ("1", "true", "yes")
    # Entra ID (Azure AD) sync, client-credentials app. Reads metadata only; per-tenant overridable.
    ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
    ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")
    ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
    # On-prem AD over LDAP (alternative to Entra). Read-only bind; metadata only.
    LDAP_URI: str = os.getenv("LDAP_URI", "")            # ldap://dc:389 or ldaps://dc:636
    LDAP_BIND_DN: str = os.getenv("LDAP_BIND_DN", "")    # service account DN or UPN
    LDAP_BIND_PASSWORD: str = os.getenv("LDAP_BIND_PASSWORD", "")
    LDAP_BASE_DN: str = os.getenv("LDAP_BASE_DN", "")    # search base, e.g. DC=corp,DC=local
    LDAP_USER_FILTER: str = os.getenv(
        "LDAP_USER_FILTER", "(&(objectClass=user)(objectCategory=person))")
    APP_NAME: str = "AI Phishing Awareness - Risk Scoring Platform"
    ENV: str = os.getenv("ENV", "development")
    # Public URL of THIS backend, for the webhook/beacon links shown in the UI. Override in prod.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # HRS aggregation: "average" | "peak" | "blend"  (see scoring.engine.score_employee)
    HRS_AGGREGATION: str = os.getenv("HRS_AGGREGATION", "blend")
    HRS_BLEND_ALPHA: float = float(os.getenv("HRS_BLEND_ALPHA", "0.5"))
    # Skip create_all on startup when using Alembic migrations.
    USE_ALEMBIC: bool = os.getenv("USE_ALEMBIC", "").lower() in ("1", "true", "yes")

    # --- production hardening ---
    # Allowed browser origins for CORS. Set the deployed frontend origin(s) in prod; never "*".
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    # Per-IP/minute cap on auth + ingestion. 0 disables (default).
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "0"))
    # Max upload size (MB) for CSV import; guards against memory exhaustion.
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "10"))

    _DEV_SECRET = "dev-only-change-me"
    _DEV_ENCRYPTION_KEY = "FXPBSe4qk56uo9FnmzrI6wqXj4YjnEdOKHeJiipZqiM="

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def secret_is_default(self) -> bool:
        return self.SECRET_KEY == self._DEV_SECRET

    def encryption_key_is_default(self) -> bool:
        return self.ENCRYPTION_KEY == self._DEV_ENCRYPTION_KEY

    def is_production(self) -> bool:
        return self.ENV.lower() in ("production", "prod")


settings = Settings()
