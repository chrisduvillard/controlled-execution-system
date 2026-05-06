"""Tests for the shared CES engineering charter."""

from __future__ import annotations

from ces.harness.prompts.engineering_charter import ENGINEERING_CHARTER, attach_engineering_charter


def test_engineering_charter_requires_traceable_surgical_changes() -> None:
    charter = ENGINEERING_CHARTER.lower()

    assert "every changed line" in charter
    assert "trace" in charter
    assert "requested work" in charter


def test_engineering_charter_rejects_speculative_complexity() -> None:
    charter = ENGINEERING_CHARTER.lower()

    assert "smallest working design" in charter
    assert "no speculative features" in charter
    assert "abstractions" in charter
    assert "configurability" in charter


def test_attach_engineering_charter_prepends_updated_charter_once() -> None:
    prompt = attach_engineering_charter("Task body")

    assert prompt.startswith(ENGINEERING_CHARTER)
    assert "Explore first" in prompt
    assert "clarify or block" in prompt
    assert prompt.endswith("Task body")
    assert prompt.count("## CES Engineering Charter") == 1
    assert attach_engineering_charter(prompt) == prompt
