"""Tests for the shared agent engineering charter prompt helper."""

from __future__ import annotations


def test_attach_engineering_charter_prepends_compact_contract() -> None:
    from ces.harness.prompts.engineering_charter import attach_engineering_charter

    prompt = attach_engineering_charter("Task body")

    assert prompt.startswith("## CES Engineering Charter")
    assert "Explore first" in prompt
    assert "clarify or block" in prompt
    assert "avoid unnecessary dependencies" in prompt
    assert prompt.endswith("Task body")


def test_attach_engineering_charter_is_idempotent() -> None:
    from ces.harness.prompts.engineering_charter import attach_engineering_charter

    once = attach_engineering_charter("Task body")
    twice = attach_engineering_charter(once)

    assert twice == once
