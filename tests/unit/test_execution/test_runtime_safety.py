"""Tests for runtime safety profile disclosure."""

from __future__ import annotations

from ces.execution.runtime_safety import safety_profile_for_runtime


def test_claude_profile_discloses_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("claude", allowed_tools=("Read", "Grep"))

    assert profile.runtime_name == "claude"
    assert profile.tool_allowlist_enforced is True
    assert profile.workspace_scoped is True
    assert profile.effective_allowed_tools == ("Read", "Grep")


def test_codex_profile_defaults_to_workspace_scoped_sandbox_not_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert profile.runtime_name == "codex"
    assert profile.tool_allowlist_enforced is False
    assert profile.workspace_scoped is True
    assert "workspace-write" in profile.network_policy
    assert "--sandbox danger-full-access" not in profile.notes


def test_codex_profile_requires_explicit_full_host_override(monkeypatch) -> None:
    monkeypatch.setenv("CES_CODEX_SANDBOX", "danger-full-access")

    profile = safety_profile_for_runtime("codex")

    assert profile.workspace_scoped is True
    assert "read-only" in profile.network_policy

    monkeypatch.setenv("CES_ALLOW_CODEX_DANGER_FULL_ACCESS", "1")
    profile = safety_profile_for_runtime("codex")

    assert profile.workspace_scoped is False
    assert "danger-full-access" in profile.network_policy


def test_codex_profile_reflects_workspace_write_sandbox_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("CES_CODEX_SANDBOX", "workspace-write")

    profile = safety_profile_for_runtime("codex")

    assert profile.tool_allowlist_enforced is False
    assert profile.workspace_scoped is True
    assert "workspace-write" in profile.network_policy
    assert "manifest allowed_tools are not enforced" in profile.notes


def test_codex_profile_invalid_sandbox_fails_closed_to_read_only(monkeypatch) -> None:
    monkeypatch.setenv("CES_CODEX_SANDBOX", "../../bin/sh")

    profile = safety_profile_for_runtime("codex")

    assert profile.workspace_scoped is True
    assert "read-only" in profile.network_policy
    assert "../../bin/sh" not in profile.notes
