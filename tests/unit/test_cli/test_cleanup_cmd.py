"""Tests for safe CES local-state cleanup."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ces.cli import app
from ces.cli.cleanup_cmd import build_cleanup_plan

runner = CliRunner()


def _get_app():
    return app


def test_cleanup_dry_run_reports_without_modifying(tmp_path: Path) -> None:
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "state.db").write_text("state", encoding="utf-8")
    gitignore = tmp_path / ".gitignore"
    original = "*.log\n# CES local state and generated artifacts\n.ces/\ndist/\n"
    gitignore.write_text(original, encoding="utf-8")

    result = runner.invoke(_get_app(), ["cleanup", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "Cleanup Preview" in result.stdout
    assert "ces cleanup --project-root" in result.stdout
    assert str(tmp_path) in result.stdout
    assert "--yes" in result.stdout
    assert ces_dir.exists()
    assert gitignore.read_text(encoding="utf-8") == original


def test_cleanup_yes_removes_only_ces_state_and_gitignore_block(tmp_path: Path) -> None:
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "state.db").write_text("state", encoding="utf-8")
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "*.log\n# CES local state and generated artifacts\n.ces/\n.venv/\ndist/\n# user block\nsecret.local\n",
        encoding="utf-8",
    )

    result = runner.invoke(_get_app(), ["cleanup", "--project-root", str(tmp_path), "--yes"])

    assert result.exit_code == 0
    assert "Cleanup Complete" in result.stdout
    assert not ces_dir.exists()
    rendered = gitignore.read_text(encoding="utf-8")
    assert "# CES local state" not in rendered
    assert "secret.local" in rendered
    assert "*.log" in rendered


def test_cleanup_rejects_symlinked_ces_dir(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".ces").symlink_to(outside)

    result = runner.invoke(_get_app(), ["cleanup", "--project-root", str(tmp_path), "--yes"])

    assert result.exit_code != 0
    assert "symlinked .ces" in result.stdout
    assert outside.exists()


def test_cleanup_rejects_dangling_symlinked_ces_dir(tmp_path: Path) -> None:
    outside = tmp_path / "missing-outside"
    (tmp_path / ".ces").symlink_to(outside)

    result = runner.invoke(_get_app(), ["cleanup", "--project-root", str(tmp_path), "--yes"])

    assert result.exit_code != 0
    assert "symlinked .ces" in result.stdout
    assert (tmp_path / ".ces").is_symlink()


def test_cleanup_rejects_symlinked_gitignore(tmp_path: Path) -> None:
    outside = tmp_path / "outside.gitignore"
    original = "# CES local state and generated artifacts\n.ces/\n"
    outside.write_text(original, encoding="utf-8")
    (tmp_path / ".gitignore").symlink_to(outside)

    result = runner.invoke(_get_app(), ["cleanup", "--project-root", str(tmp_path), "--yes"])

    assert result.exit_code != 0
    assert "symlinked .gitignore" in result.stdout
    assert outside.read_text(encoding="utf-8") == original


def test_cleanup_help_describes_dry_run_scope_and_uninstall_boundary() -> None:
    result = runner.invoke(_get_app(), ["cleanup", "--help"])

    assert result.exit_code == 0
    assert "dry-run" in result.stdout
    assert "does not uninstall" in result.stdout
    assert "symlinked" in result.stdout


def test_cleanup_plan_is_idempotent_when_nothing_exists(tmp_path: Path) -> None:
    plan = build_cleanup_plan(tmp_path)

    assert plan.has_actions is False
