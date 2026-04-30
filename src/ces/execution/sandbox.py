"""Docker sandbox for agent task execution (EXEC-01, EXEC-02, EXEC-03).

Creates isolated Docker containers with:
- No network access (network_mode="none")
- Read-only root filesystem
- Memory limits
- Empty environment (no host secrets)
- Pre-flight secret scanning on any explicitly allowlisted env vars

Threat mitigations:
- T-04-05: network_mode="none", read_only=True, mem_limit, no privileged mode
- T-04-06: _build_env returns empty dict by default, _strip_secrets removes
           key/value patterns matching known secret formats
- T-04-09: mem_limit + read_only prevents resource exhaustion

Exports:
    SandboxConfig: Frozen configuration model for sandbox containers.
    AgentSandbox: Docker container lifecycle manager with secret stripping.
"""

from __future__ import annotations

import os
import re

try:
    import docker
except ModuleNotFoundError:  # pragma: no cover - exercised via wheel smoke test
    docker = None

from ces.shared.base import CESBaseModel


class SandboxConfig(CESBaseModel):
    """Configuration for agent sandbox containers.

    All fields have secure defaults:
    - image: python:3.12-slim (minimal attack surface)
    - mem_limit: 512m (prevents memory exhaustion)
    - network_mode: none (no network access)
    - read_only: True (immutable root filesystem)
    - max_output_bytes: 1MB (prevents output DoS)
    """

    image: str = "python:3.12-slim"
    mem_limit: str = "512m"
    network_mode: str = "none"
    read_only: bool = True
    max_output_bytes: int = 1_048_576  # 1MB default


# Secret key name patterns (case-insensitive matching)
# Matches any key containing SECRET, KEY, TOKEN, PASSWORD, CREDENTIAL, or API_KEY
SECRET_KEY_PATTERNS = re.compile(r"(SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL|API_KEY)", re.IGNORECASE)

# Secret value prefix patterns -- known API key formats
SECRET_VALUE_PREFIXES = ("sk-", "pk-", "ghp_", "ghs_", "AKIA", "xoxb-", "xoxp-")

# Regex that matches an SECRET_VALUE_PREFIXES-prefixed token in free text,
# including quoted, indented, JSON-embedded, or URL-embedded occurrences.
# Used by scrub_secrets_from_text to redact secrets out of persisted stdout.
_SECRET_VALUE_IN_TEXT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in SECRET_VALUE_PREFIXES) + r")[A-Za-z0-9_\-./+=]+",
)
# Redact inline ``KEY=VALUE`` assignments even when VALUE has no known prefix.
_SECRET_KV_IN_TEXT_RE = re.compile(
    r"\b(" + SECRET_KEY_PATTERNS.pattern + r"[A-Z0-9_]*)\s*[:=]\s*['\"]?([^\s'\"]+)",
    re.IGNORECASE,
)

_REDACTION = "<REDACTED>"


def scrub_secrets_from_text(text: str) -> str:
    """Return ``text`` with likely secret material replaced by ``<REDACTED>``.

    Redacts both known-prefix tokens (``sk-``, ``AKIA``, ``ghp_``, ``xoxb-``,
    etc.) and ``KEY=VALUE`` / ``KEY: VALUE`` assignments whose key contains a
    secret-keyword substring. Used when persisting runtime subprocess output
    to ``.ces/state.db`` so that accidental secret exposure in agent output
    does not turn into persistent leakage (T-04-06 extended to stdout/stderr).
    """
    if not text:
        return text
    # Order matters: redact prefixed tokens first so they aren't matched again
    # by the key=value rule.
    step_1 = _SECRET_VALUE_IN_TEXT_RE.sub(_REDACTION, text)
    return _SECRET_KV_IN_TEXT_RE.sub(lambda m: f"{m.group(1)}={_REDACTION}", step_1)


class AgentSandbox:
    """Docker container sandbox for agent task execution (EXEC-01, EXEC-02, EXEC-03).

    Creates isolated Docker containers with:
    - No network access (network_mode="none")
    - Read-only root filesystem
    - Memory limits
    - Empty environment (no host secrets)
    - Pre-flight secret scanning on any explicitly allowlisted env vars
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        """Initialize sandbox with Docker client and configuration.

        Args:
            config: Sandbox configuration. Defaults to SandboxConfig() with
                    secure defaults (no network, read-only, 512m limit).
        """
        if docker is None:
            raise RuntimeError(
                "Docker support is not installed. Install controlled-execution-system[docker] to use sandbox execution."
            )
        self._client = docker.from_env()
        self._config = config or SandboxConfig()
        self._container = None

    @staticmethod
    def _strip_secrets(env_dict: dict[str, str]) -> dict[str, str]:
        """Remove entries with secret-like keys or values (EXEC-03).

        Scans both key names and values for known secret patterns:
        - Keys matching SECRET, KEY, TOKEN, PASSWORD, CREDENTIAL, API_KEY
        - Values starting with sk-, pk-, ghp_, ghs_, AKIA, xoxb-, xoxp-

        Args:
            env_dict: Environment variable dict to scan.

        Returns:
            Filtered dict with secret-like entries removed.
        """
        result: dict[str, str] = {}
        for key, value in env_dict.items():
            if SECRET_KEY_PATTERNS.search(key):
                continue
            if any(value.startswith(prefix) for prefix in SECRET_VALUE_PREFIXES):
                continue
            result[key] = value
        return result

    @staticmethod
    def _build_env(allowlist: list[str] | None = None) -> dict[str, str]:
        """Build container environment from allowlisted host vars only.

        Returns empty dict when no allowlist is provided (secure default).
        When an allowlist is given, only those vars are pulled from host
        env, then secret-stripped before returning.

        Args:
            allowlist: List of environment variable names to include.
                       None or empty list returns empty dict.

        Returns:
            Filtered environment dict safe for container use.
        """
        if not allowlist:
            return {}
        raw = {k: os.environ[k] for k in allowlist if k in os.environ}
        return AgentSandbox._strip_secrets(raw)

    def create_container(self, command: str, env_allowlist: list[str] | None = None) -> object:
        """Create and start a sandboxed Docker container.

        Args:
            command: Command to run inside the container.
            env_allowlist: Optional list of host env vars to pass through
                          (after secret stripping).

        Returns:
            Docker container object.
        """
        env = self._build_env(env_allowlist)
        self._container = self._client.containers.run(
            image=self._config.image,
            command=command,
            detach=True,
            network_mode=self._config.network_mode,
            read_only=self._config.read_only,
            mem_limit=self._config.mem_limit,
            environment=env,
        )
        return self._container

    def destroy_container(self) -> None:
        """Force-remove the container and clear internal reference.

        Safe to call multiple times -- no-op when no container exists.
        """
        if self._container:
            self._container.remove(force=True)
            self._container = None
