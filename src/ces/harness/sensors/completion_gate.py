"""Completion-Gate sensor pack — TestPass, Lint, TypeCheck.

These three sensors are the deterministic backbone of the Completion Gate
(P1). Each is a pure file-reader matching :class:`CoverageSensor`'s pattern:
the agent runs the underlying tool and writes a known artifact to the project
root; the sensor parses the artifact and emits structured findings.

Artifacts (all in project root, all fail-on-missing when the sensor runs):

- ``pytest-results.json`` — pytest-json-report shape: ``{"summary": {"passed": N, "failed": N, "errors": N, ...}}``
- ``ruff-report.json``    — ruff ``--output-format=json`` output: a list of violation objects
- ``mypy-report.txt``     — mypy stdout/stderr; this sensor counts ``error:`` lines

A manifest opts in to a sensor by listing it in ``verification_sensors``.
Missing artifacts are governance failures, because a configured check without
data is not a passing verification.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors.base import BaseSensor


def _project_root(context: dict) -> Path | None:
    raw = context.get("project_root", "")
    if not raw:
        return None
    return Path(raw)


def _missing_artifact_finding(artifact_name: str, suggestion: str) -> SensorFinding:
    return SensorFinding(
        category="missing_artifact",
        severity="high",
        location=artifact_name,
        message=f"Required verification artifact is missing: {artifact_name}",
        suggestion=suggestion,
    )


# ---------------------------------------------------------------------------
# TestPassSensor
# ---------------------------------------------------------------------------


class TestPassSensor(BaseSensor):
    """Reads pytest-results.json and reports test pass/fail counts."""

    __test__ = False  # don't collect as a pytest test class

    ARTIFACT_NAME = "pytest-results.json"

    def __init__(self) -> None:
        super().__init__(sensor_id="test_pass", sensor_pack="completion_gate")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        root = _project_root(context)
        if root is None:
            self._mark_skipped("No project_root in context")
            return (True, 1.0, "No project root provided; skipping pytest results check")

        artifact = root / self.ARTIFACT_NAME
        if not artifact.is_file():
            self._findings.append(
                _missing_artifact_finding(
                    self.ARTIFACT_NAME,
                    f"Run pytest with --json-report-file={self.ARTIFACT_NAME} before claiming completion",
                )
            )
            return (
                False,
                0.0,
                f"No pytest results found; run pytest with --json-report to produce {self.ARTIFACT_NAME}",
            )

        try:
            data = json.loads(artifact.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._findings.append(
                SensorFinding(
                    category="parse_error",
                    severity="medium",
                    location=str(artifact),
                    message=f"Failed to parse {self.ARTIFACT_NAME}: {exc}",
                    suggestion=f"Re-run pytest with --json-report-file={self.ARTIFACT_NAME}",
                )
            )
            return (False, 0.5, f"Failed to parse {self.ARTIFACT_NAME}: {exc}")

        summary = data.get("summary", {}) or {}
        passed = int(summary.get("passed", 0))
        failed = int(summary.get("failed", 0))
        errors = int(summary.get("errors", 0))
        total = passed + failed + errors

        details = f"{passed} passed, {failed} failed, {errors} errors"
        if failed > 0 or errors > 0:
            self._findings.append(
                SensorFinding(
                    category="test_failure",
                    severity="critical",
                    location="",
                    message=f"Test suite is not green: {details}",
                    suggestion="Fix failing tests and re-run pytest before claiming completion",
                )
            )
            score = passed / total if total > 0 else 0.0
            return (False, score, details)

        return (True, 1.0, details)


# ---------------------------------------------------------------------------
# LintSensor
# ---------------------------------------------------------------------------


class LintSensor(BaseSensor):
    """Reads ruff-report.json and reports lint violations."""

    ARTIFACT_NAME = "ruff-report.json"

    def __init__(self) -> None:
        super().__init__(sensor_id="lint", sensor_pack="completion_gate")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        root = _project_root(context)
        if root is None:
            self._mark_skipped("No project_root in context")
            return (True, 1.0, "No project root provided; skipping lint check")

        artifact = root / self.ARTIFACT_NAME
        if not artifact.is_file():
            self._findings.append(
                _missing_artifact_finding(
                    self.ARTIFACT_NAME,
                    f"Run `ruff check --output-format=json --output-file={self.ARTIFACT_NAME}` before claiming completion",
                )
            )
            return (
                False,
                0.0,
                f"No lint report found; run `ruff check --output-format=json` to produce {self.ARTIFACT_NAME}",
            )

        try:
            violations = json.loads(artifact.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self._findings.append(
                SensorFinding(
                    category="parse_error",
                    severity="medium",
                    location=str(artifact),
                    message=f"Failed to parse {self.ARTIFACT_NAME}: {exc}",
                    suggestion=f"Re-run `ruff check --output-format=json --output-file={self.ARTIFACT_NAME}`",
                )
            )
            return (False, 0.5, f"Failed to parse {self.ARTIFACT_NAME}: {exc}")

        if not isinstance(violations, list):
            self._findings.append(
                SensorFinding(
                    category="parse_error",
                    severity="medium",
                    location=str(artifact),
                    message=f"{self.ARTIFACT_NAME} is not a JSON array of violations",
                    suggestion="Use `ruff check --output-format=json`",
                )
            )
            return (False, 0.5, "Unexpected ruff-report.json shape")

        count = len(violations)
        details = f"{count} violations"

        if count == 0:
            return (True, 1.0, details)

        for v in violations:
            self._findings.append(_violation_to_finding(v))

        # Score degrades from 1.0 at 0 violations to 0.0 at 50+ violations.
        score = max(0.0, 1.0 - (count / 50.0))
        return (False, score, details)


def _violation_to_finding(v: dict) -> SensorFinding:
    """Convert a ruff JSON violation into a structured SensorFinding."""
    location = v.get("location") or {}
    row = location.get("row") if isinstance(location, dict) else None
    filename = v.get("filename", "")
    loc_str = f"{filename}:{row}" if row is not None else filename
    code = v.get("code", "")
    message = v.get("message", "")
    return SensorFinding(
        category="lint_violation",
        severity="medium",
        location=loc_str,
        message=f"{code}: {message}" if code else message,
        suggestion="Run `ruff check --fix` to auto-fix where possible",
    )


# ---------------------------------------------------------------------------
# TypeCheckSensor
# ---------------------------------------------------------------------------


_MYPY_ERROR_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):\s*error:\s*(?P<msg>.*)$")


class TypeCheckSensor(BaseSensor):
    """Reads mypy-report.txt and counts ``error:`` lines."""

    ARTIFACT_NAME = "mypy-report.txt"

    def __init__(self) -> None:
        super().__init__(sensor_id="typecheck", sensor_pack="completion_gate")

    async def _execute(self, context: dict) -> tuple[bool, float, str]:
        root = _project_root(context)
        if root is None:
            self._mark_skipped("No project_root in context")
            return (True, 1.0, "No project root provided; skipping typecheck")

        artifact = root / self.ARTIFACT_NAME
        if not artifact.is_file():
            self._findings.append(
                _missing_artifact_finding(
                    self.ARTIFACT_NAME,
                    f"Run `mypy ... > {self.ARTIFACT_NAME}` before claiming completion",
                )
            )
            return (False, 0.0, f"No mypy report found; run `mypy ... > {self.ARTIFACT_NAME}` to produce one")

        text = artifact.read_text(encoding="utf-8", errors="replace")
        errors = list(_iter_mypy_errors(text))
        count = len(errors)
        details = f"{count} errors"

        if count == 0:
            return (True, 1.0, details)

        for file, line, msg in errors:
            self._findings.append(
                SensorFinding(
                    category="type_error",
                    severity="high",
                    location=f"{file}:{line}",
                    message=msg,
                    suggestion="Resolve the type error or annotate appropriately",
                )
            )

        score = max(0.0, 1.0 - (count / 50.0))
        return (False, score, details)


def _iter_mypy_errors(text: str) -> Iterable[tuple[str, str, str]]:
    """Yield (file, line, message) for each `error:` line in mypy output."""
    for raw_line in text.splitlines():
        match = _MYPY_ERROR_RE.match(raw_line.strip())
        if match:
            yield match.group("file"), match.group("line"), match.group("msg")
