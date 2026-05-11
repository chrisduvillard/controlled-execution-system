"""Tests for harness evolution Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness_evolution.models import HarnessChangeManifest, HarnessComponentType


def _valid_manifest(**overrides: object) -> HarnessChangeManifest:
    data: dict[str, object] = {
        "change_id": "hchg-local-test-1",
        "title": "Tighten validation guidance",
        "component_type": HarnessComponentType.SYSTEM_PROMPT,
        "files_changed": ["src/ces/harness/prompts/builder.md"],
        "evidence_refs": ["dogfood:run-123#validation"],
        "failure_pattern": "Builder claimed success after proxy validation.",
        "root_cause_hypothesis": "Completion guidance did not require project-native tests.",
        "predicted_fixes": ["Agents run project-native tests before completion."],
        "predicted_regressions": ["Agents may spend more time on validation."],
        "validation_plan": ["Run dogfood scenario with proxy-validator trap."],
        "rollback_condition": "Rollback if completion success rate drops without fewer proxy validations.",
    }
    data.update(overrides)
    return HarnessChangeManifest.model_validate(data)


def test_valid_manifest_accepts_predicted_fixes_and_regressions() -> None:
    manifest = _valid_manifest()

    assert manifest.predicted_fixes == ["Agents run project-native tests before completion."]
    assert manifest.predicted_regressions == ["Agents may spend more time on validation."]
    assert manifest.status == "draft"


def test_invalid_change_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_manifest(change_id="../evil")


def test_empty_rollback_condition_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_manifest(rollback_condition="   ")


def test_secret_looking_manifest_content_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_manifest(evidence_refs=["OPENAI_API_KEY=sk-tes...3456"])


def test_unknown_manifest_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_manifest(api_key="OPENAI_API_KEY=sk-testsecret123")


def test_empty_validation_plan_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _valid_manifest(validation_plan=[])
