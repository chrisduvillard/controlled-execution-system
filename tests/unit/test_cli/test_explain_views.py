"""Tests for explain view rendering helpers."""

from __future__ import annotations

from types import SimpleNamespace

from ces.cli._explain_views import build_decisioning_explanation_lines, build_overview_explanation_lines
from ces.intent_gate.models import IntentGatePreflight, SpecificationLedger


def _preflight() -> IntentGatePreflight:
    return IntentGatePreflight(
        decision="assume_and_proceed",
        safe_next_step="Proceed after preserving OAuth callback behavior.",
        ledger=SpecificationLedger(
            goal="Fix login redirect",
            deliverable="Code change and regression test",
            audience="Authenticated users",
            assumptions=("OAuth provider config is unchanged",),
            acceptance_criteria=("Users return to original page",),
        ),
    )


def test_overview_explanation_includes_intent_gate_decision_and_safe_next_step() -> None:
    record = SimpleNamespace(
        request="Fix login redirect",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=[],
        must_not_break=[],
        open_questions={},
    )
    session = SimpleNamespace(stage="ready_to_run", next_action="run_continue", last_action="brief_captured")

    lines = build_overview_explanation_lines(
        record=record,
        session=session,
        evidence=None,
        pending_count=0,
        brief_only_fallback=False,
        intent_gate_preflight=_preflight(),
    )

    assert "Intent Gate decision: assume_and_proceed" in lines
    assert "Intent Gate safe next step: Proceed after preserving OAuth callback behavior." in lines


def test_decisioning_explanation_includes_intent_gate_summary_when_governance_enabled() -> None:
    record = SimpleNamespace(request="Fix login redirect")
    session = SimpleNamespace(stage="ready_to_run", next_action="run_continue")

    lines = build_decisioning_explanation_lines(
        record=record,
        session=session,
        manifest=None,
        evidence=None,
        pending_count=0,
        governance=True,
        intent_gate_preflight=_preflight(),
    )

    assert "Intent Gate decision: assume_and_proceed" in lines
    assert "Intent Gate preflight:" in "\n".join(lines)
