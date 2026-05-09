"""Tests for the ces profile command group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def test_profile_detect_write_persists_verification_profile(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts='-q'\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["profile", "detect", "--write"])

    assert result.exit_code == 0, result.stdout
    profile_path = tmp_path / ".ces" / "verification-profile.json"
    assert profile_path.is_file()
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    assert data["checks"]["pytest"]["status"] == "required"
    assert "verification-profile.json" in result.stdout


def test_profile_detect_project_root_writes_requested_directory_not_cwd(tmp_path: Path, monkeypatch: Any) -> None:
    source_checkout = tmp_path / "ces-source"
    target_repo = tmp_path / "target-repo"
    source_checkout.mkdir()
    target_repo.mkdir()
    monkeypatch.chdir(source_checkout)
    (target_repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\naddopts='-q'\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["profile", "detect", "--project-root", str(target_repo), "--write"])

    assert result.exit_code == 0, result.stdout
    assert (target_repo / ".ces" / "verification-profile.json").is_file()
    assert not (source_checkout / ".ces").exists()


def test_profile_detect_without_write_makes_non_persistence_explicit(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["profile", "detect"])

    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / ".ces" / "verification-profile.json").exists()
    assert "not written" in result.stdout


def test_profile_detect_project_root_without_write_does_not_create_target_state(
    tmp_path: Path, monkeypatch: Any
) -> None:
    source_checkout = tmp_path / "ces-source"
    target_repo = tmp_path / "target-repo"
    source_checkout.mkdir()
    target_repo.mkdir()
    monkeypatch.chdir(source_checkout)
    (target_repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["profile", "detect", "--project-root", str(target_repo)])

    assert result.exit_code == 0, result.stdout
    assert not (target_repo / ".ces").exists()
    assert not (source_checkout / ".ces").exists()
    assert "not written" in result.stdout


def test_profile_show_reports_existing_profile(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    profile_path = tmp_path / ".ces" / "verification-profile.json"
    profile_path.parent.mkdir()
    profile_path.write_text(
        json.dumps({"version": 1, "checks": {"pytest": {"status": "required", "configured": True, "reason": "test"}}}),
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["profile", "show"])

    assert result.exit_code == 0, result.stdout
    assert "pytest" in result.stdout
    assert "required" in result.stdout


def test_profile_doctor_exits_nonzero_without_profile(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["profile", "doctor"])

    assert result.exit_code == 1
    assert "profile detect --write" in result.stdout


def test_profile_doctor_explains_required_and_non_blocking_checks(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    profile_path = tmp_path / ".ces" / "verification-profile.json"
    profile_path.parent.mkdir()
    profile_path.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": {
                    "pytest": {"status": "required", "configured": True, "reason": "tests exist"},
                    "coverage": {"status": "advisory", "configured": False, "reason": "not universal"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["profile", "doctor"])

    assert result.exit_code == 0, result.stdout
    assert "required checks: pytest" in result.stdout
    assert "non-blocking checks: coverage" in result.stdout


def test_profile_show_and_doctor_accept_project_root(tmp_path: Path, monkeypatch: Any) -> None:
    source_checkout = tmp_path / "ces-source"
    target_repo = tmp_path / "target-repo"
    source_checkout.mkdir()
    profile_path = target_repo / ".ces" / "verification-profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps({"version": 1, "checks": {"pytest": {"status": "required", "configured": True, "reason": "test"}}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(source_checkout)

    show = runner.invoke(_get_app(), ["profile", "show", "--project-root", str(target_repo)])
    doctor = runner.invoke(_get_app(), ["profile", "doctor", "--project-root", str(target_repo)])

    assert show.exit_code == 0, show.stdout
    assert doctor.exit_code == 0, doctor.stdout
    assert "pytest" in show.stdout
    assert "required checks: pytest" in doctor.stdout
