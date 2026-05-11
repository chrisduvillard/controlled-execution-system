"""Tests for harness evolution trajectory report models."""

from __future__ import annotations

import pytest

from ces.harness_evolution.trajectory import TrajectoryReport


def test_trajectory_report_serializes_without_raw_transcript() -> None:
    report = TrajectoryReport.model_validate(
        {
            "task_run_id": "dogfood-42",
            "outcome": "fail",
            "failure_class": "validation_failure",
            "suspected_root_cause": "pytest failed after a harness policy change",
            "validation_commands_observed": ["uv run pytest tests/unit -q"],
            "proxy_validation_warnings": ["line 4: proxy validation phrase detected"],
            "evidence_pointers": ["line 3: validation command observed"],
        }
    )

    payload = report.model_dump(mode="json")

    assert payload["task_run_id"] == "dogfood-42"
    assert payload["outcome"] == "fail"
    assert "raw_transcript" not in payload
    assert payload["validation_commands_observed"] == ["uv run pytest tests/unit -q"]


def test_trajectory_report_rejects_secret_like_content() -> None:
    secret_value = "OPENAI_API_KEY=" + "sk-" + "A" * 40

    with pytest.raises(ValueError) as exc_info:
        TrajectoryReport.model_validate(
            {
                "outcome": "unknown",
                "failure_class": "unknown",
                "suspected_root_cause": secret_value,
                "validation_commands_observed": [],
                "proxy_validation_warnings": [],
                "evidence_pointers": [],
            }
        )

    assert secret_value not in str(exc_info.value)
    assert "secret-looking" in str(exc_info.value)
