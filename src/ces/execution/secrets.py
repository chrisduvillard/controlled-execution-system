"""Secret scrubbing helpers for runtime output and environment handling."""

from __future__ import annotations

import os

from ces.shared.secrets import (
    SECRET_KEY_PATTERNS,
    SECRET_VALUE_PREFIXES,
    scrub_secrets_from_text,
    scrub_secrets_recursive,
)


def strip_secret_env(env_dict: dict[str, str]) -> dict[str, str]:
    """Remove entries with secret-like keys or values."""

    result: dict[str, str] = {}
    for key, value in env_dict.items():
        if SECRET_KEY_PATTERNS.search(key):
            continue
        if any(value.startswith(prefix) for prefix in SECRET_VALUE_PREFIXES):
            continue
        result[key] = value
    return result


def build_allowed_env(allowlist: list[str] | None = None) -> dict[str, str]:
    """Build a filtered environment from allowlisted host variables only."""

    if not allowlist:
        return {}
    raw = {key: os.environ[key] for key in allowlist if key in os.environ}
    return strip_secret_env(raw)


__all__ = [
    "build_allowed_env",
    "scrub_secrets_from_text",
    "scrub_secrets_recursive",
    "strip_secret_env",
]
