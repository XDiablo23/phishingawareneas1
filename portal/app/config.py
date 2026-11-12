"""
Portal configuration. Everything is env-overridable so the launcher can
wire the portal to the running PhishAwareness instance without code edits.
The PhishAwareness connection can ALSO be set at runtime from the admin
Settings screen (stored in the DB) - these are the boot defaults / fallback.
"""
from __future__ import annotations

import os


def _b(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    APP_NAME = "PhishAwareness Awareness & Remediation Portal"
    VERSION = "1.0.0"
    PORT = int(os.getenv("PORTAL_PORT", "8100"))

    # Portal's OWN database (separate service, separate DB).
    DATABASE_URL = os.getenv("PORTAL_DATABASE_URL", "sqlite:///./portal.db")

    # Portal's own auth (employees log in natively here).
    SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", "dev-portal-secret-change-me")
    ACCESS_TOKEN_TTL_MIN = int(os.getenv("PORTAL_TOKEN_TTL_MIN", "720"))
    # Encrypts secret columns at rest (Setting.pa_service_token,
    # TicketConfig.auth_header_value) - a Fernet key, i.e. 32 url-safe
    # base64 bytes. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY = os.getenv(
        "PORTAL_ENCRYPTION_KEY", "JtPEm73SDlQUbkhEOtyiUrb5csd-3OTetBCSIGjvGPM=")

    # PhishAwareness REST connection (boot defaults; overridable in Settings).
    PA_BASE_URL = os.getenv("PA_BASE_URL", "http://127.0.0.1:8000")
    PA_TENANT_ID = os.getenv("PA_TENANT_ID", "")
    # Service token for the /portal automation surface (generated on the
    # PhishAwareness side: Manage -> Integration -> rotate
    # "portal_service_token"). Replaces a stored operator email+password.
    PA_SERVICE_TOKEN = os.getenv("PA_SERVICE_TOKEN", "")
    PA_VERIFY_TLS = _b(os.getenv("PA_VERIFY_TLS", "1"))

    # Escalation policy (boot defaults; overridable in Settings).
    # onboarding_floor: baseline HRS pushed to PhishAwareness once a new hire
    #   finishes mandatory onboarding (Moderate band = 25..49).
    # inperson_after_days: how long a user may stay High/Critical before the
    #   portal marks them for in-person awareness and raises a ticket.
    ONBOARDING_FLOOR = float(os.getenv("PORTAL_ONBOARDING_FLOOR", "35"))
    INPERSON_AFTER_DAYS = int(os.getenv("PORTAL_INPERSON_AFTER_DAYS", "30"))

    # Background auto-sync loop (0 = disabled; the launcher sets e.g. 300).
    AUTO_SYNC_SECONDS = int(os.getenv("PORTAL_AUTO_SYNC_SECONDS", "0"))

    ENV = os.getenv("PORTAL_ENV", os.getenv("ENV", "development"))
    # The SPA is served same-origin, so cross-origin access is OFF by default
    # ("" -> no cross-origin allowed). Set an explicit origin list, or "*", to
    # open it up. "*" is refused in production.
    CORS_ORIGINS = os.getenv("PORTAL_CORS_ORIGINS", "")
    # Per-IP request cap per minute on the auth endpoints (0 = disabled;
    # set e.g. 30 in production to blunt credential brute-forcing).
    RATE_LIMIT_PER_MINUTE = int(os.getenv("PORTAL_RATE_LIMIT_PER_MINUTE", "0"))

    _DEV_SECRET = "dev-portal-secret-change-me"
    _DEV_ENCRYPTION_KEY = "JtPEm73SDlQUbkhEOtyiUrb5csd-3OTetBCSIGjvGPM="

    def is_production(self) -> bool:
        return (self.ENV or "").lower() in ("production", "prod")

    def secret_is_default(self) -> bool:
        return self.SECRET_KEY == self._DEV_SECRET

    def encryption_key_is_default(self) -> bool:
        return self.ENCRYPTION_KEY == self._DEV_ENCRYPTION_KEY

    def cors_list(self) -> list[str]:
        v = (self.CORS_ORIGINS or "").strip()
        if v == "*":
            return [] if self.is_production() else ["*"]
        return [o.strip() for o in v.split(",") if o.strip()]


settings = Settings()
