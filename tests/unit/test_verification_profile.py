"""Tests for project-aware verification profiles."""

from __future__ import annotations

import json
from pathlib import Path

from ces.verification.profile import VerificationProfile, VerificationStatus, load_verification_profile
from ces.verification.profile_detector import detect_verification_profile, write_verification_profile


def test_loads_profile_and_exposes_required_optional_unavailable(tmp_path: Path) -> None:
    profile_path = tmp_path / ".ces" / "verification-profile.json"
    profile_path.parent.mkdir()
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": {
                    "pytest": {"status": "required", "configured": True, "reason": "pytest configured"},
                    "ruff": {"status": "optional", "configured": True, "reason": "ruff installed"},
                    "mypy": {"status": "unavailable", "configured": False, "reason": "mypy not configured"},
                    "coverage": {"status": "advisory", "configured": True, "reason": "coverage available"},
                },
            }
        ),
        encoding="utf-8",
    )

    profile = load_verification_profile(tmp_path)

    assert profile is not None
    assert profile.requirement_for("pytest").status is VerificationStatus.REQUIRED
    assert profile.requirement_for("ruff").status is VerificationStatus.OPTIONAL
    assert profile.requirement_for("mypy").status is VerificationStatus.UNAVAILABLE
    assert profile.requirement_for("coverage").status is VerificationStatus.ADVISORY
    assert profile.is_required("pytest") is True
    assert profile.is_required("ruff") is False


def test_detector_marks_configured_tools_and_writes_profile(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["pytest", "ruff", "mypy-extensions"]

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )

    profile = detect_verification_profile(tmp_path)
    assert profile.requirement_for("pytest").status is VerificationStatus.REQUIRED
    assert profile.requirement_for("ruff").status is VerificationStatus.REQUIRED
    assert profile.requirement_for("mypy").status is VerificationStatus.UNAVAILABLE
    assert profile.requirement_for("coverage").status is VerificationStatus.ADVISORY

    path = write_verification_profile(tmp_path, profile)
    assert path == tmp_path / ".ces" / "verification-profile.json"
    persisted = VerificationProfile.model_validate_json(path.read_text(encoding="utf-8"))
    assert persisted.requirement_for("ruff").configured is True
    assert persisted.requirement_for("mypy").configured is False


def test_detector_does_not_require_pytest_for_generic_tests_directory(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")

    profile = detect_verification_profile(tmp_path)

    assert profile.requirement_for("pytest").status is VerificationStatus.UNAVAILABLE
    assert profile.requirement_for("pytest").required is False


def test_detector_marks_configured_node_package_scripts(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "bun test", "build": "bun build ./src/index.ts"}}),
        encoding="utf-8",
    )
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    profile = detect_verification_profile(tmp_path)

    assert profile.requirement_for("node-test").status is VerificationStatus.REQUIRED
    assert profile.requirement_for("node-build").status is VerificationStatus.REQUIRED
    assert profile.requirement_for("node-lint").status is VerificationStatus.UNAVAILABLE
    assert "package.json test script detected" in profile.requirement_for("node-test").reason
