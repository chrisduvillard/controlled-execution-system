"""Root CLI front-door contract tests."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def test_root_help_routes_beginner_greenfield_work_without_overclaiming() -> None:
    result = runner.invoke(
        _get_app(),
        ["--help"],
        env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.stdout
    lowered = result.stdout.lower()
    assert "start here" in lowered
    assert "ces ship" in result.stdout
    assert "ces build --gsd" in result.stdout
    assert "ces mri" in result.stdout
    assert "read-only" in lowered
    assert "local" in lowered
    forbidden = (
        "auto-deploy",
        "auto-merge",
        "hosted control plane",
        "universal sandbox",
        "zero human intervention",
    )
    assert all(term not in lowered for term in forbidden)
