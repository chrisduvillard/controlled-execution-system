"""Tests for shared execution pipeline helpers."""

from __future__ import annotations

from types import SimpleNamespace

from ces.execution.pipeline import (
    COMPLETION_CLAIM_INSTRUCTIONS,
    SIMPLICITY_GUARD_INSTRUCTIONS,
    build_completion_gate_prompt_fragment,
    build_completion_gate_prompt_fragment_from_values,
    build_manifest_execution_prompt,
    completion_gate_enabled,
    normalize_runtime_execution,
)


def test_build_manifest_execution_prompt_matches_completion_gate_contract() -> None:
    manifest = SimpleNamespace(
        manifest_id="M-123",
        description="Add checkout discounts",
        affected_files=("src/app.py",),
        verification_sensors=("test_pass",),
        acceptance_criteria=("Discounts apply at checkout",),
        mcp_servers=("context7",),
    )

    prompt = build_manifest_execution_prompt(manifest)

    assert "Manifest ID:\nM-123" in prompt
    assert "MCP grounding requested" in prompt
    assert "Acceptance criteria you must address" in prompt
    assert "Discounts apply at checkout" in prompt
    assert COMPLETION_CLAIM_INSTRUCTIONS in prompt
    assert SIMPLICITY_GUARD_INSTRUCTIONS in prompt
    assert "Prefer the smallest boring solution" in prompt
    assert "complexity_notes" in prompt
    assert "ces:completion" in prompt


def test_completion_gate_fragment_omits_gate_when_no_real_sensor_tuple() -> None:
    manifest = SimpleNamespace(verification_sensors=[], acceptance_criteria=("criterion",))

    assert completion_gate_enabled(manifest) is False
    assert build_completion_gate_prompt_fragment(manifest) == ""


def test_completion_gate_fragment_from_values_matches_manifest_fragment() -> None:
    manifest = SimpleNamespace(
        verification_sensors=("test_pass", "lint"),
        acceptance_criteria=("Criterion one",),
    )

    assert build_completion_gate_prompt_fragment_from_values(
        acceptance_criteria=["Criterion one"],
        verification_sensors=["test_pass", "lint"],
    ) == build_completion_gate_prompt_fragment(manifest)


def test_completion_gate_requires_complexity_notes() -> None:
    prompt = build_completion_gate_prompt_fragment_from_values(
        acceptance_criteria=["A tiny CLI works"],
        verification_sensors=["test_pass"],
    )

    assert '"complexity_notes"' in prompt
    assert "new_abstractions" in prompt
    assert "new_dependencies" in prompt
    assert "simpler_alternative_considered" in prompt
    assert "unnecessary complexity" in prompt


def test_normalize_runtime_execution_accepts_wrapped_model_dump() -> None:
    class RuntimeResult:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            return {"mode": mode, "exit_code": 0}

    result = SimpleNamespace(runtime_result=RuntimeResult())

    assert normalize_runtime_execution(result) == {"mode": "json", "exit_code": 0}
