"""Secret scrubbing helpers for runtime output and environment handling."""

from __future__ import annotations

import os
import re
from typing import Any

# Secret key name patterns (case-insensitive matching).
SECRET_KEY_PATTERNS = re.compile(r"(SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY)", re.IGNORECASE)
SECRET_KV_KEY_PATTERN = r"[A-Z0-9_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY)[A-Z0-9_]*"  # noqa: S105

# Secret value prefix patterns -- known API key formats.
SECRET_VALUE_PREFIXES = ("sk-", "pk-", "ghp_", "ghs_", "AKIA", "xoxb-", "xoxp-")

_SECRET_VALUE_IN_TEXT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in SECRET_VALUE_PREFIXES) + r")[A-Za-z0-9_\-./+=]+",
)
_SECRET_KV_IN_TEXT_RE = re.compile(
    r"\b(" + SECRET_KV_KEY_PATTERN + r")\s*[:=]\s*['\"]?([^\s'\"]+)",
    re.IGNORECASE,
)

_REDACTION = "<REDACTED>"


def scrub_secrets_from_text(text: str) -> str:
    """Return ``text`` with likely secret material replaced by ``<REDACTED>``."""
    if not text:
        return text
    step_1 = _SECRET_VALUE_IN_TEXT_RE.sub(_REDACTION, text)
    return _SECRET_KV_IN_TEXT_RE.sub(lambda m: f"{m.group(1)}={_REDACTION}", step_1)


def scrub_secrets_recursive(value: Any) -> Any:
    """Recursively scrub likely secrets from JSON-compatible evidence payloads.

    Text leaves are redacted, mapping keys are preserved for schema stability,
    and list/tuple containers keep their original broad shape so persisted
    evidence remains reviewable without leaking secret values.
    """
    if isinstance(value, str):
        return scrub_secrets_from_text(value)
    if isinstance(value, dict):
        return {key: scrub_secrets_recursive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_secrets_recursive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_secrets_recursive(item) for item in value)
    return value


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
