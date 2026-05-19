"""Tests for objective-bound proof binding fingerprints."""

from __future__ import annotations

from ces.verification.completion_contract import (
    AcceptanceCriterion,
    BehaviorDelta,
    CompletionContract,
    VerificationCommand,
)


def _contract(**overrides) -> CompletionContract:
    payload = {
        "request": "Add invoice notes to CSV exports",
        "project_type": "python-cli",
        "acceptance_criteria": (AcceptanceCriterion(id="AC-001", text="CSV exports include notes"),),
        "inferred_commands": (
            VerificationCommand(id="tests", kind="test", command="pytest", expected_exit_codes=(0,)),
        ),
        "runtime": {
            "name": "codex",
            "project_mode": "brownfield",
            "constraints": ["keep CSV headers stable"],
            "must_not_break": ["existing CSV importers"],
            "source_of_truth": "README.md and current tests",
            "critical_flows": ["export invoices", "import exported CSV"],
        },
        "behavior_delta": BehaviorDelta(
            modified=("CSV export writes an optional notes column.",),
            preserved=("Existing CSV importers still accept old exports.",),
        ),
    }
    payload.update(overrides)
    return CompletionContract(**payload)


def test_proof_binding_hash_is_stable_for_same_objective_context() -> None:
    from ces.verification.proof_binding import build_proof_binding

    first = build_proof_binding(_contract())
    second = build_proof_binding(_contract())

    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert first.to_dict()["project_mode"] == "brownfield"
    assert first.to_dict()["objective"] == "Add invoice notes to CSV exports"


def test_proof_binding_hash_changes_when_objective_changes() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(_contract(request="Add supplier notes to PDFs")).content_hash

    assert changed != original


def test_proof_binding_hash_changes_when_brownfield_constraints_change() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(
        _contract(
            runtime={
                "name": "codex",
                "project_mode": "brownfield",
                "constraints": ["keep CSV headers stable"],
                "must_not_break": ["legacy invoice totals"],
                "source_of_truth": "docs/domain.md",
                "critical_flows": ["export invoices"],
            }
        )
    ).content_hash

    assert changed != original


def test_proof_binding_hash_changes_when_verification_commands_change() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(
        _contract(
            inferred_commands=(
                VerificationCommand(id="tests", kind="test", command="pytest -q", expected_exit_codes=(0,)),
            )
        )
    ).content_hash

    assert changed != original


def test_proof_binding_scrubs_inline_secret_before_export_and_hash() -> None:
    from ces.verification.proof_binding import build_proof_binding

    binding = build_proof_binding(
        _contract(
            inferred_commands=(
                VerificationCommand(
                    id="smoke",
                    kind="smoke",
                    command="OPENAI_API_KEY=sk-test-secret-value python app.py",
                    expected_exit_codes=(0,),
                ),
            )
        )
    )

    exported = str(binding.to_dict())
    assert "sk-test-secret-value" not in exported
    assert "OPENAI_API_KEY=<REDACTED>" in exported
