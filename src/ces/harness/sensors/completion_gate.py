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
Missing artifacts are governance failures when an explicit verification profile
requires that exact artifact. Otherwise, successful equivalent commands in the
completion claim can satisfy the sensor as reduced evidence.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Iterable

from ces.harness.models.sensor_result import SensorFinding
from ces.harness.sensors.base import BaseSensor
from ces.verification.profile import VerificationCheck, VerificationStatus, load_verification_profile


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


def _profile_requirement(context: dict, check_name: str) -> VerificationCheck | None:
    if context.get("profile_trusted") is False:
        return None
    root = _project_root(context)
    if root is None:
        return None
    profile = load_verification_profile(root)
    if profile is None:
        return None
    return profile.requirement_for(check_name)


def _missing_artifact_profile_result(
    sensor: BaseSensor,
    context: dict,
    *,
    check_name: str,
    artifact_name: str,
) -> tuple[bool, float, str] | None:
    requirement = _profile_requirement(context, check_name)
    if requirement is None:
        return None
    sensor._set_verification_metadata(
        configured=requirement.configured,
        required=requirement.required,
        reason=requirement.reason,
    )
    if requirement.status is VerificationStatus.REQUIRED:
        return None
    reason = f"{check_name} is {requirement.status.value}: {requirement.reason}"
    sensor._mark_skipped(reason)
    return (True, 1.0, f"Missing {artifact_name} ignored because {reason}")


def missing_artifact_result_with_reduced_evidence(
    sensor: BaseSensor,
    context: dict,
    *,
    check_name: str,
    artifact_name: str,
    command_markers: tuple[str, ...],
    require_artifact_path: bool = False,
    summary_percent_min: float | None = None,
) -> tuple[bool, float, str] | None:
    """Return a non-blocking reduced-evidence result for missing artifacts.

    Explicit verification profiles still win: if a profile requires the exact
    artifact, the sensor remains blocking. Without an explicit profile, a
    successful completion-claim command that invokes the same tool can be
    accepted as reduced evidence instead of false-blocking otherwise valid work.
    """

    profile_result = _missing_artifact_profile_result(
        sensor,
        context,
        check_name=check_name,
        artifact_name=artifact_name,
    )
    if profile_result is not None:
        return profile_result
    requirement = _profile_requirement(context, check_name)
    if requirement is not None and requirement.status is VerificationStatus.REQUIRED:
        return None
    if not _has_successful_completion_command(
        context,
        command_markers,
        require_artifact_path=require_artifact_path,
        summary_percent_min=summary_percent_min,
    ):
        return None
    reason = f"structured {artifact_name} missing; accepted equivalent successful completion command"
    sensor._set_verification_metadata(configured=False, required=False, reason=reason)
    sensor._mark_skipped(reason)
    return (True, 0.8, f"Missing {artifact_name}; accepted reduced evidence from completion claim")


def _has_successful_completion_command(
    context: dict,
    markers: tuple[str, ...],
    *,
    require_artifact_path: bool = False,
    summary_percent_min: float | None = None,
) -> bool:
    for entry in context.get("completion_verification_commands", ()) or ():
        try:
            exit_code = int(_field(entry, "exit_code") or 0)
        except ValueError:
            continue
        if exit_code != 0:
            continue
        if require_artifact_path and not _artifact_path_exists(context, _field(entry, "artifact_path")):
            continue
        if summary_percent_min is not None and not _summary_reports_min_percent(
            _field(entry, "summary"), summary_percent_min
        ):
            continue
        if _command_invokes_marker(_field(entry, "command"), markers):
            return True
    return False


def _command_invokes_marker(command: str, markers: tuple[str, ...]) -> bool:
    try:
        tokens = tuple(token.casefold() for token in shlex.split(command, comments=True, posix=True))
    except ValueError:
        tokens = tuple(command.casefold().split())
    if not tokens:
        return False
    invoked = set(_invoked_tools(tokens))
    return any(marker.casefold() in invoked for marker in markers)


def _invoked_tools(tokens: tuple[str, ...]) -> tuple[str, ...]:
    index = _first_executable_index(tokens)
    if index is None:
        return ()
    tools: list[str] = []
    executable = _tool_name(tokens[index])
    tools.append(executable)
    if executable.startswith("python"):
        module = _python_module(tokens, index + 1)
        if module:
            tools.append(module)
    if executable in {"uv", "poetry", "pipx", "npx"}:
        wrapped = _wrapped_tool(tokens, index + 1)
        if wrapped:
            tools.append(wrapped)
            if wrapped.startswith("python"):
                module = _python_module(tokens, tokens.index(wrapped, index + 1) + 1) if wrapped in tokens else ""
                if module:
                    tools.append(module)
    if "pytest" in tools and any(part == "--cov" or part.startswith("--cov=") for part in tokens):
        tools.append("pytest-cov")
    if "trace" in tools and {"--count", "--summary"}.intersection(tokens):
        tools.append("trace-coverage")
    return tuple(tools)


def _first_executable_index(tokens: tuple[str, ...]) -> int | None:
    for index, part in enumerate(tokens):
        if "=" in part and not part.startswith("-") and part.split("=", 1)[0].isidentifier():
            continue
        if part == "env":
            continue
        return index
    return None


def _python_module(tokens: tuple[str, ...], start: int) -> str:
    for index in range(start, len(tokens)):
        if tokens[index] == "-m" and index + 1 < len(tokens):
            return tokens[index + 1].rsplit(".", 1)[-1]
        if not tokens[index].startswith("-"):
            return ""
    return ""


def _wrapped_tool(tokens: tuple[str, ...], start: int) -> str:
    for index in range(start, len(tokens)):
        part = tokens[index]
        if part not in {"run", "exec", "x"}:
            continue
        for candidate in tokens[index + 1 :]:
            if candidate.startswith("-"):
                continue
            return _tool_name(candidate)
    return ""


def _tool_name(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _artifact_path_exists(context: dict, artifact_path: str) -> bool:
    if not artifact_path:
        return False
    root = _project_root(context)
    if root is None:
        return False
    path = (root / artifact_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return path.exists()


_PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")


def _summary_reports_min_percent(summary: str, minimum: float) -> bool:
    percentages = [float(match.group("value")) for match in _PERCENT_RE.finditer(summary)]
    return bool(percentages) and max(percentages) >= minimum


def _field(entry: Any, name: str) -> str:
    value = entry.get(name, "") if isinstance(entry, dict) else getattr(entry, name, "")
    return "" if value is None else str(value)


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
            profile_result = missing_artifact_result_with_reduced_evidence(
                self,
                context,
                check_name="pytest",
                artifact_name=self.ARTIFACT_NAME,
                command_markers=("pytest",),
            )
            if profile_result is not None:
                return profile_result
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
            profile_result = missing_artifact_result_with_reduced_evidence(
                self,
                context,
                check_name="ruff",
                artifact_name=self.ARTIFACT_NAME,
                command_markers=("ruff", "tabnanny"),
            )
            if profile_result is not None:
                return profile_result
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
            profile_result = missing_artifact_result_with_reduced_evidence(
                self,
                context,
                check_name="mypy",
                artifact_name=self.ARTIFACT_NAME,
                command_markers=("mypy", "pyright", "pyre", "tsc", "py_compile", "compileall"),
            )
            if profile_result is not None:
                return profile_result
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
