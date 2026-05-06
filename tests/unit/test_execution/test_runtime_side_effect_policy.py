"""Tests for runtime side-effect approval policy."""

from __future__ import annotations

from ces.execution import runtime_safety
from ces.execution.runtime_safety import safety_profile_for_runtime


def test_codex_side_effect_risk_blocks_unattended_approval_without_acceptance() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert hasattr(runtime_safety, "runtime_side_effects_block_auto_approval")
    assert runtime_safety.runtime_side_effects_block_auto_approval(profile, accepted=False) is True


def test_codex_side_effect_risk_requires_pre_execution_consent() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert hasattr(runtime_safety, "runtime_side_effects_require_pre_execution_consent")
    assert runtime_safety.runtime_side_effects_require_pre_execution_consent(profile, accepted=False) is True


def test_claude_safe_profile_does_not_require_pre_execution_consent() -> None:
    profile = safety_profile_for_runtime("claude", allowed_tools=("Read", "Edit"))

    assert runtime_safety.runtime_side_effects_require_pre_execution_consent(profile, accepted=False) is False


def test_codex_side_effect_risk_allows_unattended_approval_when_accepted() -> None:
    profile = safety_profile_for_runtime("codex", allowed_tools=("Read",))

    assert runtime_safety.runtime_side_effects_block_auto_approval(profile, accepted=True) is False


def test_claude_tool_allowlist_does_not_require_side_effect_acceptance() -> None:
    profile = safety_profile_for_runtime("claude", allowed_tools=("Read", "Edit"))

    assert runtime_safety.runtime_side_effects_block_auto_approval(profile, accepted=False) is False
