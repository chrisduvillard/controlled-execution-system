"""Tests for execution._subprocess_env.build_subprocess_env.

Pins the security contracts of the env allowlist used when CES spawns
``claude``/``codex`` subprocesses. Before 0.1.2, only the runtime adapters
scrubbed the env; the CLI provider inherited the full parent env, which
leaked AWS_SECRET_ACCESS_KEY, DATABASE_URL, etc. into every LLM subprocess.
These tests guard against that regression.
"""

from __future__ import annotations

import pytest

from ces.execution._subprocess_env import build_subprocess_env


class TestBuildSubprocessEnv:
    def test_allowlisted_base_key_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        env = build_subprocess_env()
        assert env["PATH"] == "/usr/bin:/bin"

    def test_non_allowlisted_secret_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "AK" + "IA" + "-leak-do-not-pass")
        monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
        env = build_subprocess_env()
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "DATABASE_URL" not in env

    def test_lc_prefix_vars_are_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LC_* prefix expansion (line 84): non-base LC_* locale vars pass through."""
        monkeypatch.setenv("LC_NUMERIC", "fr_FR.UTF-8")
        monkeypatch.setenv("LC_TIME", "en_US.UTF-8")
        env = build_subprocess_env()
        assert env["LC_NUMERIC"] == "fr_FR.UTF-8"
        assert env["LC_TIME"] == "en_US.UTF-8"

    def test_extra_keys_are_added(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Adapter-specific keys (e.g. ANTHROPIC_API_KEY) are admitted via extra_keys."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk" + "-" + "ant-test")
        env = build_subprocess_env(extra_keys=("ANTHROPIC_API_KEY",))
        assert env["ANTHROPIC_API_KEY"] == "sk" + "-" + "ant-test"
        # Without extra_keys, the same var is stripped.
        env_default = build_subprocess_env()
        assert "ANTHROPIC_API_KEY" not in env_default
