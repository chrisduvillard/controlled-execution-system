from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from ces.intent_gate.models import IntentGatePreflight, IntentQuestion, SpecificationLedger


def _ledger(**overrides: object) -> SpecificationLedger:
    values: dict[str, object] = {
        "goal": "Add a small README wording improvement.",
        "deliverable": "Updated README text.",
        "audience": "Project maintainers.",
        "scope": ("README wording only",),
        "non_goals": ("No behavior changes",),
        "constraints": ("Keep existing formatting",),
        "inputs": ("User request",),
        "tool_permissions": ("Read and edit repository files",),
        "assumptions": ("Make the smallest clear wording change",),
        "open_questions": (),
        "decisions": ("Proceed with low-risk docs edit",),
        "acceptance_criteria": ("README wording is clearer",),
        "verification_plan": ("Review diff",),
        "risks": ("Accidental wording drift",),
    }
    values.update(overrides)
    return SpecificationLedger(**values)


def test_minimal_valid_preflight_model_accepted() -> None:
    preflight = IntentGatePreflight(
        decision="proceed",
        ledger=_ledger(),
        safe_next_step="Inspect README and apply the requested wording-only edit.",
    )

    assert re.fullmatch(r"igp-[0-9a-f]{16}", preflight.preflight_id)
    assert re.fullmatch(r"[0-9a-f]{64}", preflight.content_hash)
    assert preflight.created_at.tzinfo is not None
    assert preflight.decision == "proceed"


def test_question_requires_why_it_matters() -> None:
    with pytest.raises(ValidationError):
        IntentQuestion(question="Which failure mode should auth preserve?", why_it_matters="")


def test_ledger_rejects_secret_like_text() -> None:
    with pytest.raises(ValidationError, match="secret-like"):
        _ledger(inputs=("Use API_KEY=sk-test1234567890",))


def test_preflight_content_hash_is_stable_excluding_generated_fields() -> None:
    ledger = _ledger()
    first = IntentGatePreflight(decision="proceed", ledger=ledger, safe_next_step="Inspect README.")
    second = IntentGatePreflight(decision="proceed", ledger=ledger, safe_next_step="Inspect README.")

    assert first.preflight_id == f"igp-{first.content_hash[:16]}"
    assert second.preflight_id == first.preflight_id
    assert first.content_hash == second.content_hash


def test_preflight_rejects_mismatched_content_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash does not match"):
        IntentGatePreflight(
            decision="proceed",
            ledger=_ledger(),
            safe_next_step="Inspect README.",
            content_hash="0" * 64,
        )
