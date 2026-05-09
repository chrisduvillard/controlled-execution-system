"""Unit tests for the Completion-Gate sensors (P1b).

TestPassSensor reads `pytest-results.json`, LintSensor reads `ruff-report.json`,
and TypeCheckSensor reads `mypy-report.txt` from the project root. All three
follow CoverageSensor's pattern: pure file-readers that fail when configured
artifacts are missing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ces.harness.sensors.completion_gate import (
    LintSensor,
    TestPassSensor,
    TypeCheckSensor,
)
from ces.harness.sensors.test_coverage import CoverageSensor


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _profile(root: Path, checks: dict[str, dict[str, object]]) -> None:
    profile_path = root / ".ces" / "verification-profile.json"
    profile_path.parent.mkdir()
    profile_path.write_text(json.dumps({"version": 1, "checks": checks}), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestPassSensor
# ---------------------------------------------------------------------------


class TestTestPassSensor:
    """TestPassSensor reads pytest-results.json from project root."""

    @pytest.mark.asyncio
    async def test_no_project_root_skips(self) -> None:
        sensor = TestPassSensor()
        passed, score, _ = await sensor._execute({})
        assert sensor._skipped_flag is True
        assert passed is True
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_no_artifact_fails(self, tmp_path: Path) -> None:
        sensor = TestPassSensor()
        passed, _, details = await sensor._execute({"project_root": str(tmp_path)})
        assert sensor._skipped_flag is False
        assert "No pytest results" in details
        assert passed is False
        assert sensor._findings[0].category == "missing_artifact"

    @pytest.mark.asyncio
    async def test_missing_artifact_is_non_blocking_when_profile_marks_optional(self, tmp_path: Path) -> None:
        _profile(
            tmp_path,
            {"pytest": {"status": "optional", "configured": True, "reason": "pytest is available but optional"}},
        )
        sensor = TestPassSensor()
        result = await sensor.run({"project_root": str(tmp_path)})
        assert result.passed is True
        assert result.skipped is True
        assert result.required is False
        assert result.configured is True
        assert result.reason == "pytest is available but optional"

    @pytest.mark.asyncio
    async def test_profile_is_ignored_when_context_marks_it_untrusted(self, tmp_path: Path) -> None:
        _profile(
            tmp_path,
            {"pytest": {"status": "optional", "configured": True, "reason": "pytest is available but optional"}},
        )
        sensor = TestPassSensor()
        result = await sensor.run({"project_root": str(tmp_path), "profile_trusted": False})
        assert result.passed is False
        assert result.skipped is False
        assert result.required is None
        assert result.findings[0].category == "missing_artifact"

    @pytest.mark.asyncio
    async def test_all_passed_yields_pass(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pytest-results.json",
            json.dumps({"summary": {"passed": 412, "failed": 0, "errors": 0}}),
        )
        sensor = TestPassSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == 1.0
        assert "412 passed" in details

    @pytest.mark.asyncio
    async def test_any_failure_yields_fail(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pytest-results.json",
            json.dumps({"summary": {"passed": 408, "failed": 4, "errors": 0}}),
        )
        sensor = TestPassSensor()
        passed, score, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score < 1.0
        # At least one finding describes the failure
        assert any(f.category == "test_failure" for f in sensor._findings)

    @pytest.mark.asyncio
    async def test_errors_count_as_failures(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "pytest-results.json",
            json.dumps({"summary": {"passed": 410, "failed": 0, "errors": 2}}),
        )
        sensor = TestPassSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False

    @pytest.mark.asyncio
    async def test_corrupt_json_yields_failure_finding(self, tmp_path: Path) -> None:
        _write(tmp_path / "pytest-results.json", "{ not valid json")
        sensor = TestPassSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert any(f.category == "parse_error" for f in sensor._findings)


# ---------------------------------------------------------------------------
# LintSensor
# ---------------------------------------------------------------------------


class TestLintSensor:
    """LintSensor reads ruff-report.json from project root."""

    @pytest.mark.asyncio
    async def test_no_project_root_skips(self) -> None:
        sensor = LintSensor()
        passed, score, _ = await sensor._execute({})
        assert sensor._skipped_flag is True
        assert passed is True
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_no_artifact_fails(self, tmp_path: Path) -> None:
        sensor = LintSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert sensor._skipped_flag is False
        assert passed is False
        assert sensor._findings[0].category == "missing_artifact"

    @pytest.mark.asyncio
    async def test_missing_artifact_still_fails_when_profile_marks_required(self, tmp_path: Path) -> None:
        _profile(tmp_path, {"ruff": {"status": "required", "configured": True, "reason": "ruff configured"}})
        sensor = LintSensor()
        result = await sensor.run({"project_root": str(tmp_path)})
        assert result.passed is False
        assert result.required is True
        assert result.configured is True
        assert result.reason == "ruff configured"
        assert result.findings[0].category == "missing_artifact"

    @pytest.mark.asyncio
    async def test_empty_violations_passes(self, tmp_path: Path) -> None:
        _write(tmp_path / "ruff-report.json", json.dumps([]))
        sensor = LintSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == 1.0
        assert "0 violations" in details

    @pytest.mark.asyncio
    async def test_violations_fail_with_findings(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "ruff-report.json",
            json.dumps(
                [
                    {
                        "code": "E501",
                        "message": "Line too long",
                        "filename": "src/auth/login.py",
                        "location": {"row": 42, "column": 80},
                    },
                    {
                        "code": "F401",
                        "message": "unused import",
                        "filename": "src/app.py",
                        "location": {"row": 3, "column": 1},
                    },
                ]
            ),
        )
        sensor = LintSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score < 1.0
        assert "2 violations" in details
        # Each violation produces a finding tied to its file
        assert len(sensor._findings) == 2
        locations = {f.location for f in sensor._findings}
        assert "src/auth/login.py:42" in locations

    @pytest.mark.asyncio
    async def test_corrupt_json_yields_failure_finding(self, tmp_path: Path) -> None:
        _write(tmp_path / "ruff-report.json", "[invalid")
        sensor = LintSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert any(f.category == "parse_error" for f in sensor._findings)


# ---------------------------------------------------------------------------
# TypeCheckSensor
# ---------------------------------------------------------------------------


class TestTypeCheckSensor:
    """TypeCheckSensor reads mypy-report.txt and counts `error:` lines."""

    @pytest.mark.asyncio
    async def test_no_project_root_skips(self) -> None:
        sensor = TypeCheckSensor()
        passed, score, _ = await sensor._execute({})
        assert sensor._skipped_flag is True
        assert passed is True
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_no_artifact_fails(self, tmp_path: Path) -> None:
        sensor = TypeCheckSensor()
        passed, _, _ = await sensor._execute({"project_root": str(tmp_path)})
        assert sensor._skipped_flag is False
        assert passed is False
        assert sensor._findings[0].category == "missing_artifact"

    @pytest.mark.asyncio
    async def test_missing_artifact_is_non_blocking_when_profile_marks_unavailable(self, tmp_path: Path) -> None:
        _profile(tmp_path, {"mypy": {"status": "unavailable", "configured": False, "reason": "mypy not installed"}})
        sensor = TypeCheckSensor()
        result = await sensor.run({"project_root": str(tmp_path)})
        assert result.passed is True
        assert result.skipped is True
        assert result.required is False
        assert result.configured is False
        assert result.reason == "mypy not installed"

    @pytest.mark.asyncio
    async def test_zero_errors_passes(self, tmp_path: Path) -> None:
        _write(tmp_path / "mypy-report.txt", "Success: no issues found in 250 source files\n")
        sensor = TypeCheckSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is True
        assert score == 1.0
        assert "0 errors" in details

    @pytest.mark.asyncio
    async def test_errors_fail_with_findings(self, tmp_path: Path) -> None:
        report = (
            "src/app.py:42: error: Incompatible types in assignment  [assignment]\n"
            "src/util.py:7: error: Argument 1 has incompatible type  [arg-type]\n"
            "Found 2 errors in 2 files (checked 250 source files)\n"
        )
        _write(tmp_path / "mypy-report.txt", report)
        sensor = TypeCheckSensor()
        passed, score, details = await sensor._execute({"project_root": str(tmp_path)})
        assert passed is False
        assert score < 1.0
        assert "2 errors" in details
        assert len(sensor._findings) == 2
        assert any("src/app.py:42" in f.location for f in sensor._findings)


class TestCoverageProfileAwareness:
    @pytest.mark.asyncio
    async def test_missing_coverage_is_non_blocking_when_profile_marks_advisory(self, tmp_path: Path) -> None:
        _profile(tmp_path, {"coverage": {"status": "advisory", "configured": True, "reason": "coverage is advisory"}})
        sensor = CoverageSensor()
        result = await sensor.run({"project_root": str(tmp_path)})
        assert result.passed is True
        assert result.skipped is True
        assert result.required is False
        assert result.configured is True
        assert result.reason == "coverage is advisory"
