"""Tests for CLI runtime detection and resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _StubRuntime:
    def __init__(self, name: str, detected: bool = True) -> None:
        self.runtime_name = name
        self._detected = detected

    def detect(self) -> bool:
        return self._detected


def _clear_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("CODEX_HOME", "CODEX_SANDBOX", "CLAUDECODE", "CLAUDE_CODE"):
        monkeypatch.delenv(var, raising=False)


class TestRuntimeRegistry:
    """Tests for runtime resolution order."""

    def test_explicit_runtime_wins(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )

        runtime = registry.resolve_runtime(runtime_name="claude")

        assert runtime.runtime_name == "claude"

    def test_preferred_runtime_used_when_no_explicit_runtime(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )

        runtime = registry.resolve_runtime(
            runtime_name="auto",
            preferred_runtime="claude",
        )

        assert runtime.runtime_name == "claude"

    def test_current_host_detection_beats_fallback(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )

        with patch.object(registry, "detect_current_host_runtime", return_value="claude"):
            runtime = registry.resolve_runtime(runtime_name="auto")

        assert runtime.runtime_name == "claude"

    def test_fallback_prefers_codex_then_claude(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )

        with patch.object(registry, "detect_current_host_runtime", return_value=None):
            runtime = registry.resolve_runtime(runtime_name="auto")

        assert runtime.runtime_name == "codex"


class TestHostRuntimeDetection:
    """detect_current_host_runtime() reads CODEX/CLAUDE env vars."""

    def test_codex_home_env_detects_codex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        _clear_host_env(monkeypatch)
        monkeypatch.setenv("CODEX_HOME", "/some/path")
        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )
        assert registry.detect_current_host_runtime() == "codex"

    def test_no_env_var_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        _clear_host_env(monkeypatch)
        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )
        assert registry.detect_current_host_runtime() is None


class TestRuntimeResolutionEdges:
    """Edge cases in resolve_runtime: dedup, failed detection, no runtime found."""

    def test_preferred_with_no_host_falls_through_to_fallback(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex"),
            claude_runtime=_StubRuntime("claude"),
        )
        with patch.object(registry, "detect_current_host_runtime", return_value=None):
            runtime = registry.resolve_runtime(runtime_name="auto", preferred_runtime="claude")
        assert runtime.runtime_name == "claude"

    def test_dedup_skips_repeated_candidate_and_finds_next(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex", detected=False),
            claude_runtime=_StubRuntime("claude", detected=True),
        )
        with patch.object(registry, "detect_current_host_runtime", return_value="codex"):
            runtime = registry.resolve_runtime(runtime_name="auto", preferred_runtime="codex")
        assert runtime.runtime_name == "claude"

    def test_raises_runtime_error_when_no_runtime_detects(self) -> None:
        from ces.execution.runtimes.registry import RuntimeRegistry

        registry = RuntimeRegistry(
            codex_runtime=_StubRuntime("codex", detected=False),
            claude_runtime=_StubRuntime("claude", detected=False),
        )
        with (
            patch.object(registry, "detect_current_host_runtime", return_value=None),
            pytest.raises(RuntimeError, match="No supported runtime"),
        ):
            registry.resolve_runtime(runtime_name="auto")
