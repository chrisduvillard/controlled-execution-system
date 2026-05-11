"""Tests for deterministic harness trajectory distillation."""

from __future__ import annotations

from ces.harness_evolution.distiller import distill_transcript


def test_distill_transcript_extracts_failure_shape_without_raw_content() -> None:
    secret_value = "OPENAI_API_KEY=" + "sk-" + "A" * 40
    transcript = f"""
run_id: dogfood-42
Thought: I'll just inspect the file and assume the tests would pass.
Command: uv run pytest tests/unit/test_harness.py -q
FAILED tests/unit/test_harness.py::test_policy
AssertionError: proxy validation accepted
{secret_value}
""".strip()

    report = distill_transcript(transcript, source_path="runs/dogfood-42.log")

    assert report.task_run_id == "dogfood-42"
    assert report.outcome == "fail"
    assert report.failure_class == "validation_failure"
    assert report.suspected_root_cause == "validation command failed"
    assert report.validation_commands_observed == ["uv run pytest tests/unit/test_harness.py -q"]
    assert report.proxy_validation_warnings
    assert "source: runs/dogfood-42.log" in report.evidence_pointers
    rendered = report.to_markdown()
    assert "sk-" + "A" * 8 not in rendered
    assert "AssertionError: proxy validation accepted" not in rendered


def test_distill_transcript_detects_pass_and_unknown_without_validation_commands() -> None:
    pass_report = distill_transcript("run id: green-1\n10 passed in 1.2s")
    unknown_report = distill_transcript("notes only, no validation command")

    assert pass_report.task_run_id == "green-1"
    assert pass_report.outcome == "pass"
    assert pass_report.failure_class == "none"
    assert unknown_report.outcome == "unknown"
    assert unknown_report.failure_class == "unknown"
