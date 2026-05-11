"""Deterministic distillation of raw transcripts into harness trajectory reports."""

from __future__ import annotations

from pathlib import Path

from ces.execution.secrets import scrub_secrets_from_text
from ces.harness_evolution.patterns import (
    classify_failure,
    classify_outcome,
    evidence_pointers,
    extract_task_run_id,
    extract_validation_commands,
    proxy_validation_warnings,
    suspected_root_cause,
)
from ces.harness_evolution.trajectory import TrajectoryReport


def distill_transcript(transcript: str, *, source_path: str | None = None) -> TrajectoryReport:
    """Create a compact, secret-scrubbed report from a raw transcript string."""

    scrubbed = scrub_secrets_from_text(transcript)
    lines = scrubbed.splitlines()
    commands = extract_validation_commands(lines)
    outcome = classify_outcome(lines)
    failure_class = classify_failure(outcome, commands)
    warnings = proxy_validation_warnings(lines)
    return TrajectoryReport(
        task_run_id=extract_task_run_id(lines),
        outcome=outcome,  # type: ignore[arg-type]
        failure_class=failure_class,
        suspected_root_cause=suspected_root_cause(outcome, failure_class),
        validation_commands_observed=commands,
        proxy_validation_warnings=warnings,
        evidence_pointers=evidence_pointers(lines=lines, source_path=source_path, commands=commands, warnings=warnings),
    )


def distill_transcript_file(path: Path) -> TrajectoryReport:
    """Read and distill a transcript file."""

    return distill_transcript(path.read_text(encoding="utf-8"), source_path=str(path))
