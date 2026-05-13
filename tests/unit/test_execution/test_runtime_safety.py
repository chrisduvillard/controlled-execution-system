"""Tests for runtime safety profile disclosure."""

from __future__ import annotations

from ces.execution.runtime_safety import safety_profile_for_runtime


def test_claude_profile_discloses_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("claude", allowed_tools=("Read", "Grep"))

    assert profile.runtime_name == "claude"
    assert profile.tool_allowlist_enforced is True
    assert profile.workspace_scoped is True
    assert profile.effective_allowed_tools == ("Read", "Grep")


def test_codex_profile_discloses_danger_full_access_not_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert profile.runtime_name == "codex"
    assert profile.tool_allowlist_enforced is False
    assert profile.workspace_scoped is False
    assert "danger-full-access" in profile.network_policy
    assert "danger-full-access" in profile.notes


def test_codex_profile_reflects_workspace_write_sandbox_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("CES_CODEX_SANDBOX", "workspace-write")

    profile = safety_profile_for_runtime("codex")

    assert profile.tool_allowlist_enforced is False
    assert profile.workspace_scoped is True
    assert "workspace-write" in profile.network_policy
    assert "manifest allowed_tools are not enforced" in profile.notes
