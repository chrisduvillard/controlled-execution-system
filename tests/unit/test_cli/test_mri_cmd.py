"""Tests for the ces mri command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _write_python_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["pytest", "ruff", "mypy"]

[project.scripts]
demo = "demo.cli:app"

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.12"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (root / ".ces").mkdir()
    (root / ".ces" / "verification-profile.json").write_text("{}\n", encoding="utf-8")


def test_mri_markdown_is_default_and_reports_project_health(tmp_path: Path, monkeypatch: Any) -> None:
    _write_python_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["mri"])

    assert result.exit_code == 0, result.stdout
    assert "# Project MRI" in result.stdout
    assert "Maturity:" in result.stdout
    assert "shareable-app" in result.stdout or "production-candidate" in result.stdout
    assert "python-cli" in result.stdout
    assert "Recommended next CES actions" in result.stdout


def test_mri_json_is_valid_deterministic_and_machine_readable(tmp_path: Path) -> None:
    _write_python_repo(tmp_path)

    first = runner.invoke(_get_app(), ["mri", "--project-root", str(tmp_path), "--format", "json"])
    second = runner.invoke(_get_app(), ["mri", "--project-root", str(tmp_path), "--format", "json"])

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["schema_version"] == 1
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["project_type"] == "python-cli"
    assert payload["maturity"] in {"shareable-app", "production-candidate", "operated-product"}
    assert any(signal["name"] == "pytest" for signal in payload["signals"])
    assert all("value" not in finding for finding in payload["risk_findings"])


def test_mri_project_root_scans_requested_directory_without_mutating(tmp_path: Path, monkeypatch: Any) -> None:
    source_checkout = tmp_path / "source"
    target_repo = tmp_path / "target"
    source_checkout.mkdir()
    target_repo.mkdir()
    monkeypatch.chdir(source_checkout)
    _write_python_repo(target_repo)
    before = sorted(path.relative_to(target_repo).as_posix() for path in target_repo.rglob("*"))

    result = runner.invoke(_get_app(), ["mri", "--project-root", str(target_repo), "--format", "markdown"])

    after = sorted(path.relative_to(target_repo).as_posix() for path in target_repo.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (source_checkout / ".ces").exists()
    assert str(target_repo.resolve()) in result.stdout


def test_mri_reports_secret_hygiene_without_printing_secret_values(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
    (tmp_path / ".env").write_text("API_TOKEN=super-secret-value\n", encoding="utf-8")

    result = runner.invoke(_get_app(), ["mri", "--project-root", str(tmp_path), "--format", "markdown"])

    assert result.exit_code == 0, result.stdout
    assert ".env" in result.stdout
    assert "API_TOKEN" in result.stdout
    assert "super-secret-value" not in result.stdout
    assert "secret" in result.stdout.lower()
