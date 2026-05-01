"""Tests for runtime safety profile disclosure."""

from __future__ import annotations

from ces.execution.runtime_safety import safety_profile_for_runtime


def test_claude_profile_discloses_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("claude", allowed_tools=("Read", "Grep"))

    assert profile.runtime_name == "claude"
    assert profile.tool_allowlist_enforced is True
    assert profile.workspace_scoped is True
    assert profile.effective_allowed_tools == ("Read", "Grep")


def test_codex_profile_discloses_workspace_write_not_tool_allowlist() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert profile.runtime_name == "codex"
    assert profile.tool_allowlist_enforced is False
    assert profile.workspace_scoped is True
    assert "workspace-write" in profile.notes
