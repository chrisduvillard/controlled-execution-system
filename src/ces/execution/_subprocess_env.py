"""Shared subprocess-env allowlist for CES CLI spawns.

Both the runtime adapters (``src/ces/execution/runtimes/adapters.py``) and the
inline CLI provider (``src/ces/execution/providers/cli_provider.py``) spawn
``claude``/``codex`` subprocesses. Before 0.1.2, only the runtime adapters
scrubbed the environment; the CLI provider inherited the full parent env,
which leaked vars like ``AWS_SECRET_ACCESS_KEY`` and ``DATABASE_URL`` into
every LLM subprocess. Consolidating the allowlist here ensures both spawn
paths apply the same policy.
"""

from __future__ import annotations

import os
from typing import Iterable

# Keys always preserved. These are the minimum set needed for a CLI tool to
# run on Windows, macOS, Linux; they include locale, proxy, and CA bundle
# settings that users rely on in managed environments.
BASE_RUNTIME_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "USERNAME",
    "SHELL",
    "TERM",
    "COLORTERM",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PWD",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NO_COLOR",
    "FORCE_COLOR",
    "CI",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
)

# Additional prefixes kept verbatim (e.g. every LC_* locale variable).
BASE_RUNTIME_ENV_PREFIXES: tuple[str, ...] = ("LC_",)


def build_subprocess_env(extra_keys: Iterable[str] = ()) -> dict[str, str]:
    """Build an allowlist-filtered env dict from the current process env.

    Callers pass ``extra_keys`` for adapter-specific variables (Codex wants
    ``CODEX_HOME``/``OPENAI_API_KEY``; Claude wants ``ANTHROPIC_API_KEY``).
    Everything else — AWS creds, DATABASE_URL, GITHUB_TOKEN, CI secrets —
    is stripped before the subprocess inherits.
    """
    env: dict[str, str] = {}
    for key in dict.fromkeys((*BASE_RUNTIME_ENV_KEYS, *extra_keys)):
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    for key, value in os.environ.items():
        if key.startswith(BASE_RUNTIME_ENV_PREFIXES) and key not in env:
            env[key] = value
    return env
