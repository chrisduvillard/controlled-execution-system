from __future__ import annotations

from ces.intent_gate.classifier import classify_intent


def test_clear_low_risk_task_proceeds_when_acceptance_exists() -> None:
    preflight = classify_intent(
        request="Add unit tests for the date parser helper.",
        constraints=("Keep public API unchanged",),
        acceptance_criteria=("New unit tests cover valid and invalid dates",),
        must_not_break=("Existing parser behavior",),
        project_mode="maintenance",
        non_interactive=False,
    )

    assert preflight.decision == "proceed"
    assert preflight.ledger.open_questions == ()
    assert any("unit tests cover valid and invalid dates" in item for item in preflight.ledger.acceptance_criteria)


def test_readme_wording_ambiguous_task_assumes_and_proceeds() -> None:
    preflight = classify_intent(
        request="Tighten up the README wording in the install section.",
        constraints=(),
        acceptance_criteria=(),
        must_not_break=(),
        project_mode="maintenance",
        non_interactive=False,
    )

    assert preflight.decision == "assume_and_proceed"
    assert any("minimal" in assumption.lower() for assumption in preflight.ledger.assumptions)
    assert "Inspect" in preflight.safe_next_step


def test_auth_task_asks_when_failure_mode_missing() -> None:
    preflight = classify_intent(
        request="Change auth token refresh handling.",
        constraints=(),
        acceptance_criteria=(),
        must_not_break=(),
        project_mode="maintenance",
        non_interactive=False,
    )

    assert preflight.decision == "ask"
    assert preflight.ledger.open_questions
    assert any("failure mode" in question.question.lower() for question in preflight.ledger.open_questions)
    assert preflight.ledger.risks


def test_noninteractive_high_risk_database_delete_task_blocks() -> None:
    preflight = classify_intent(
        request="Delete old database rows from production users table.",
        constraints=(),
        acceptance_criteria=(),
        must_not_break=(),
        project_mode="maintenance",
        non_interactive=True,
    )

    assert preflight.decision == "blocked"
    assert preflight.ledger.open_questions
    assert "clarification" in preflight.safe_next_step.lower()
