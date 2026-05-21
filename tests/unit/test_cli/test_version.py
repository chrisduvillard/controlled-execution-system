"""Tests for top-level CES CLI version output."""

from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def test_top_level_version_option_reports_package_version() -> None:
    """`ces --version` exits successfully and prints the CES package version."""
    from ces import __version__

    result = runner.invoke(_get_app(), ["--version"])

    assert result.exit_code == 0, result.stdout
    assert f"controlled-execution-system {__version__}" in result.stdout


def test_source_tree_version_fallback_reads_pyproject() -> None:
    import ces

    root = Path(__file__).resolve().parents[3]
    project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

    assert ces._source_tree_version() == project_version
