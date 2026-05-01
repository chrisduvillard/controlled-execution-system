"""Secret scrubbing helpers for runtime output and environment handling."""

from __future__ import annotations

import os
import re

# Secret key name patterns (case-insensitive matching).
SECRET_KEY_PATTERNS = re.compile(r"(SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY)", re.IGNORECASE)

# Secret value prefix patterns -- known API key formats.
SECRET_VALUE_PREFIXES = ("sk-", "pk-", "ghp_", "ghs_", "AKIA", "xoxb-", "xoxp-")

_SECRET_VALUE_IN_TEXT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in SECRET_VALUE_PREFIXES) + r")[A-Za-z0-9_\-./+=]+",
)
_SECRET_KV_IN_TEXT_RE = re.compile(
    r"\b(" + SECRET_KEY_PATTERNS.pattern + r"[A-Z0-9_]*)\s*[:=]\s*['\"]?([^\s'\"]+)",
    re.IGNORECASE,
)

_REDACTION = "<REDACTED>"


def scrub_secrets_from_text(text: str) -> str:
    """Return ``text`` with likely secret material replaced by ``<REDACTED>``."""
    if not text:
        return text
    step_1 = _SECRET_VALUE_IN_TEXT_RE.sub(_REDACTION, text)
    return _SECRET_KV_IN_TEXT_RE.sub(lambda m: f"{m.group(1)}={_REDACTION}", step_1)


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
