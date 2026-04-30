"""CES configuration management using pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from ces.shared.crypto import DEV_DEFAULT_HMAC_MARKER


class CESSettings(BaseSettings):
    """CES application settings loaded from ``CES_`` environment variables."""

    log_level: str = "INFO"
    log_format: str = "json"

    # Crypto and audit settings.
    audit_hmac_secret: str = f"ces-dev-hmac-secret-{DEV_DEFAULT_HMAC_MARKER}"

    # Demo mode: return canned helper responses when no real provider is set.
    demo_mode: bool = False

    # Local runtime defaults.
    default_model_id: str = "claude-sonnet-4-6"
    default_runtime: str = "codex"
    model_roster: list[str] = [
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "gpt-5",
    ]

    model_config = SettingsConfigDict(
        env_prefix="CES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def validate_production_secrets(self) -> list[str]:
        """Check for development-default secrets that must be overridden in production."""
        warnings: list[str] = []
        if DEV_DEFAULT_HMAC_MARKER in self.audit_hmac_secret:
            warnings.append(
                "CES_AUDIT_HMAC_SECRET is using the development default. Set a unique secret for production (T-07-01)."
            )
        return warnings

    def enforce_resolved_secrets(self, audit_secret: bytes) -> None:
        """Raise ``RuntimeError`` if the *resolved* audit secret is still the dev default.

        Belt-and-suspenders: ``load_audit_hmac_secret`` already rejects the
        env-side dev default, but this guards against any future loader that
        bypasses that helper. Call after secret resolution, with the bytes
        that will actually be used.

        Skipped under demo mode (``CES_DEMO_MODE=1``) so offline demos run
        without provisioning real secrets.
        """
        if self.demo_mode:
            return
        if DEV_DEFAULT_HMAC_MARKER.encode("utf-8") in audit_secret:
            raise RuntimeError(
                "CES production secrets misconfigured: resolved audit HMAC secret "
                "contains the development default marker (T-07-01)."
            )
