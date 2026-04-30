"""Runtime registry and resolution for local agent CLIs."""

from __future__ import annotations

import os

from ces.execution.runtimes.adapters import ClaudeRuntimeAdapter, CodexRuntimeAdapter
from ces.execution.runtimes.protocol import AgentRuntimeProtocol


class RuntimeRegistry:
    """Resolve the local runtime to use for a task."""

    def __init__(
        self,
        codex_runtime: AgentRuntimeProtocol | None = None,
        claude_runtime: AgentRuntimeProtocol | None = None,
    ) -> None:
        self._runtimes: dict[str, AgentRuntimeProtocol] = {
            "codex": codex_runtime or CodexRuntimeAdapter(),
            "claude": claude_runtime or ClaudeRuntimeAdapter(),
        }

    def detect_current_host_runtime(self) -> str | None:
        """Best-effort detection of the current host CLI."""
        if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"):
            return "codex"
        if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
            return "claude"
        return None

    def resolve_runtime(
        self,
        runtime_name: str = "auto",
        preferred_runtime: str | None = None,
    ) -> AgentRuntimeProtocol:
        """Resolve runtime using explicit -> preferred -> host -> fallback order."""
        candidates: list[str] = []
        if runtime_name and runtime_name != "auto":
            candidates.append(runtime_name)
        elif preferred_runtime:
            candidates.append(preferred_runtime)
            detected = self.detect_current_host_runtime()
            if detected is not None:
                candidates.append(detected)
            candidates.extend(["codex", "claude"])
        else:
            detected = self.detect_current_host_runtime()
            if detected is not None:
                candidates.append(detected)
            candidates.extend(["codex", "claude"])

        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            runtime = self._runtimes.get(candidate)
            if runtime is not None and runtime.detect():
                return runtime
        available = ", ".join(sorted(self._runtimes))
        raise RuntimeError(f"No supported runtime detected. Tried: {', '.join(seen)}. Available: {available}")
