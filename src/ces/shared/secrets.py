"""Shared secret redaction helpers."""

from __future__ import annotations

import re
from typing import Any

# Secret key name patterns (case-insensitive matching).
SECRET_KEY_PATTERNS = re.compile(
    r"(SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY|CLIENT_SECRET)",
    re.IGNORECASE,
)
SECRET_KV_KEY_PATTERN = (
    r"[A-Z0-9_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY|PRIVATE_KEY|CLIENT_SECRET)[A-Z0-9_]*"  # noqa: S105
)

# Secret value prefix patterns -- known API key formats.
SECRET_VALUE_PREFIXES = (
    "sk-",
    "pk-",
    "ghp_",
    "ghs_",
    "github_pat_",
    "glpat-",
    "AKIA",
    "xoxb-",
    "xoxp-",
    "xoxc-",
    "xoxa-",
    "xoxr-",
    "xoxs-",
    "xoxe-",
    "xapp-",
)

_SECRET_VALUE_IN_TEXT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in SECRET_VALUE_PREFIXES) + r")[A-Za-z0-9_\-./+=]+",
)
_SECRET_KV_IN_TEXT_RE = re.compile(
    r"\b(" + SECRET_KV_KEY_PATTERN + r")\s*[:=]\s*['\"]?([^\s'\"]+)",
    re.IGNORECASE,
)
_JWT_IN_TEXT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_CREDENTIAL_URL_RE = re.compile(
    r"\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
    re.IGNORECASE,
)
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_RE = re.compile(
    r'("private_key"\s*:\s*")([^"]+)(")',
    re.IGNORECASE,
)
_GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID_RE = re.compile(
    r'("private_key_id"\s*:\s*")([^"]+)(")',
    re.IGNORECASE,
)

_REDACTION = "<REDACTED>"


def scrub_secrets_from_text(text: str) -> str:
    """Return ``text`` with likely secret material replaced by ``<REDACTED>``."""

    if not text:
        return text
    scrubbed = _PRIVATE_KEY_BLOCK_RE.sub(_REDACTION, text)
    scrubbed = _CREDENTIAL_URL_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}:{_REDACTION}@", scrubbed)
    scrubbed = _GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_RE.sub(lambda m: f"{m.group(1)}{_REDACTION}{m.group(3)}", scrubbed)
    scrubbed = _GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID_RE.sub(
        lambda m: f"{m.group(1)}{_REDACTION}{m.group(3)}", scrubbed
    )
    scrubbed = _JWT_IN_TEXT_RE.sub(_REDACTION, scrubbed)
    scrubbed = _SECRET_VALUE_IN_TEXT_RE.sub(_REDACTION, scrubbed)
    return _SECRET_KV_IN_TEXT_RE.sub(lambda m: f"{m.group(1)}={_REDACTION}", scrubbed)


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


__all__ = [
    "SECRET_KEY_PATTERNS",
    "SECRET_VALUE_PREFIXES",
    "scrub_secrets_from_text",
    "scrub_secrets_recursive",
]
