"""Fresh-project CLI JSON contract regressions from installed-wheel dogfood."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> typer.Typer:
    from ces.cli import app

    return app


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json_or_none(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def test_global_json_scan_emits_machine_readable_inventory(tmp_path: Path) -> None:
    """`ces --json scan` should honor global JSON mode for automation."""
    _write(tmp_path / "pyproject.toml", '[project]\nname = "fresh-project"\n')

    result = runner.invoke(_get_app(), ["--json", "scan", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["root"] == str(tmp_path.resolve())
    assert payload["scanned_at"]
    assert payload["modules"] == [
        {
            "path": "pyproject.toml",
            "type": "python",
            "name": tmp_path.name,
        }
    ]
    assert payload["generated_files"] == []
    assert payload["codeowners"] == []
    assert payload["report_path"].endswith(".ces/brownfield/scan.json")
    assert (tmp_path / ".ces" / "brownfield" / "scan.json").is_file()


def test_global_json_scan_parse_error_uses_json_error_envelope(tmp_path: Path) -> None:
    """Typer usage errors should stay parseable when root --json is present."""
    result = runner.invoke(_get_app(), ["--json", "scan", "--definitely-not-an-option", str(tmp_path)])

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["error"]["type"] == "usage_error"
    assert payload["error"]["title"] == "Usage Error"
    assert "No such option" in payload["error"]["message"]
    assert "--definitely-not-an-option" in payload["error"]["message"]
    assert payload["error"]["exit_code"] == 2


def test_programmatic_non_standalone_usage_errors_still_raise_original_click_exception() -> None:
    """Embedding callers keep Click's standalone_mode=False exception contract."""
    command = typer.main.get_command(_get_app())

    with pytest.raises(click.NoSuchOption) as exc_info:
        command.main(args=["--json", "scan", "--definitely-not-an-option", "."], standalone_mode=False)

    assert exc_info.value.exit_code == 2


class _VendoredStyleUsageError(Exception):
    """Minimal stand-in for Typer's vendored Click exceptions in newer wheels."""

    exit_code = 2

    def format_message(self) -> str:
        return "No such option: --definitely-not-an-option"


def test_global_json_usage_errors_from_vendored_click_are_json_enveloped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Installed wheels must catch Typer-vendored Click errors under root --json."""
    command = typer.main.get_command(_get_app())

    def raise_vendored_usage_error(*args: object, **kwargs: object) -> None:
        raise _VendoredStyleUsageError

    monkeypatch.setattr(typer.core.TyperGroup, "main", raise_vendored_usage_error)

    with pytest.raises(SystemExit) as exc_info:
        command.main(args=["--json", "scan", "--definitely-not-an-option", "."], standalone_mode=True)

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"]["type"] == "usage_error"
    assert payload["error"]["title"] == "Usage Error"
    assert payload["error"]["message"] == "No such option: --definitely-not-an-option"
    assert payload["error"]["exit_code"] == 2


def test_command_local_json_does_not_activate_root_json_usage_envelope() -> None:
    """Only root --json promises machine-readable usage errors."""
    result = runner.invoke(_get_app(), ["scan", "--json"], catch_exceptions=False)

    assert result.exit_code == 2
    assert result.stderr.startswith("Usage:")
    assert _json_or_none(result.stderr) is None
