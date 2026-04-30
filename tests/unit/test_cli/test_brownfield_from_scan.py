"""Tests for the ces brownfield register --from-scan flag."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _prepare_project(tmp_path: Path) -> None:
    """Create a minimal .ces/ project so brownfield commands can resolve it."""
    app = _get_app()
    result = runner.invoke(app, ["init", "scan-import-test"])
    assert result.exit_code == 0, result.stdout


def _write_scan(tmp_path: Path, *, modules: list[dict[str, str]] | None = None) -> Path:
    scan_dir = tmp_path / ".ces" / "brownfield"
    scan_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "root": str(tmp_path),
        "scanned_at": "2026-04-18T00:00:00+00:00",
        "modules": modules
        or [
            {"path": "pyproject.toml", "type": "python", "name": "example"},
            {"path": "frontend/package.json", "type": "node", "name": "frontend"},
        ],
        "generated_files": [],
        "codeowners": [],
    }
    scan_path = scan_dir / "scan.json"
    scan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return scan_path


class TestBrownfieldRegisterFromScan:
    """Tests for ces brownfield register --from-scan."""

    def test_from_scan_flag_registers_one_entry_per_module(self, tmp_path: Path, monkeypatch: object) -> None:
        """--from-default-scan drafts one behavior entry per detected module."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _prepare_project(tmp_path)
        _write_scan(tmp_path)
        app = _get_app()
        result = runner.invoke(
            app,
            ["brownfield", "register", "--from-default-scan"],
        )
        assert result.exit_code == 0, result.stdout
        # Surface output should mention both module names so the user
        # can see exactly what was drafted.
        assert "example" in result.stdout
        assert "frontend" in result.stdout

    def test_from_scan_accepts_explicit_path(self, tmp_path: Path, monkeypatch: object) -> None:
        """--from-scan accepts an explicit path to the scan.json file."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _prepare_project(tmp_path)
        alt = tmp_path / "alt-scan.json"
        alt.write_text(
            json.dumps(
                {
                    "root": str(tmp_path),
                    "scanned_at": "2026-04-18T00:00:00+00:00",
                    "modules": [{"path": "a/pyproject.toml", "type": "python", "name": "alpha"}],
                    "generated_files": [],
                    "codeowners": [],
                }
            ),
            encoding="utf-8",
        )
        app = _get_app()
        result = runner.invoke(
            app,
            ["brownfield", "register", "--from-scan", str(alt)],
        )
        assert result.exit_code == 0, result.stdout
        assert "alpha" in result.stdout

    def test_missing_scan_file_is_a_clean_error(self, tmp_path: Path, monkeypatch: object) -> None:
        """--from-default-scan with no scan.json present exits non-zero without stack trace."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _prepare_project(tmp_path)
        app = _get_app()
        result = runner.invoke(
            app,
            ["brownfield", "register", "--from-default-scan"],
        )
        assert result.exit_code != 0

    def test_from_scan_and_system_conflict(self, tmp_path: Path, monkeypatch: object) -> None:
        """Passing --from-default-scan together with --system is rejected as contradictory."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _prepare_project(tmp_path)
        _write_scan(tmp_path)
        app = _get_app()
        result = runner.invoke(
            app,
            [
                "brownfield",
                "register",
                "--from-default-scan",
                "--system",
                "legacy-system",
                "--description",
                "something",
            ],
        )
        assert result.exit_code != 0
