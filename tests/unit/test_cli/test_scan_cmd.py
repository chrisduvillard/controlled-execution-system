"""Tests for the ces scan command (scan_cmd module)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestCesScan:
    """Tests for the ces scan command."""

    def test_scan_is_registered(self) -> None:
        """The app has a scan command registered."""
        app = _get_app()
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0

    def test_writes_scan_json(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces scan` writes a JSON report under .ces/brownfield/."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "pyproject.toml", '[project]\nname = "example"\n')
        app = _get_app()
        result = runner.invoke(app, ["scan"])
        assert result.exit_code == 0, result.stdout
        out = tmp_path / ".ces" / "brownfield" / "scan.json"
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "modules" in data
        assert "generated_files" in data
        assert "codeowners" in data
        assert "scanned_at" in data

    def test_scan_dry_run_does_not_bootstrap_or_write_report(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces scan --dry-run` previews inventory without creating local CES state."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "pyproject.toml", '[project]\nname = "example"\n')
        app = _get_app()

        result = runner.invoke(app, ["scan", "--dry-run"])

        assert result.exit_code == 0, result.stdout
        assert "dry run" in result.stdout.lower()
        assert not (tmp_path / ".ces").exists()

    def test_scan_bootstraps_valid_local_project_when_uninitialized(self, tmp_path: Path, monkeypatch: object) -> None:
        """A pre-init scan must not leave a partial .ces/ directory."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "pyproject.toml", '[project]\nname = "example"\n')
        app = _get_app()
        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0, result.stdout
        assert (tmp_path / ".ces" / "config.yaml").is_file()
        assert (tmp_path / ".ces" / "keys" / "ed25519_private.key").is_file()
        assert (tmp_path / ".ces" / "state.db").is_file()

    def test_detects_python_module(self, tmp_path: Path, monkeypatch: object) -> None:
        """Detects a pyproject.toml as a Python module."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "pyproject.toml", '[project]\nname = "myproj"\n')
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        types = {m["type"] for m in data["modules"]}
        assert "python" in types

    def test_detects_python_package_without_pyproject(self, tmp_path: Path, monkeypatch: object) -> None:
        """Detects simple runnable Python packages even without pyproject.toml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "idea_ledger" / "__init__.py", '"""Idea Ledger."""\n')
        _write(tmp_path / "idea_ledger" / "__main__.py", "def main():\n    return 0\n")
        _write(tmp_path / "idea_ledger" / "cli.py", "def cli():\n    return 0\n")
        _write(tmp_path / "tests" / "test_cli.py", "def test_smoke():\n    assert True\n")

        app = _get_app()
        result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0, result.stdout
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        assert {
            "path": "idea_ledger/__init__.py",
            "type": "python",
            "name": "idea_ledger",
        } in data["modules"]

    def test_detects_node_module(self, tmp_path: Path, monkeypatch: object) -> None:
        """Detects a package.json inside a subfolder as a Node module."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "frontend" / "package.json", '{"name": "ui"}\n')
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        paths = {m["path"] for m in data["modules"]}
        assert any("frontend/package.json" in p.replace("\\", "/") for p in paths)

    def test_skips_node_modules_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        """Does not descend into node_modules/ when looking for manifests."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(tmp_path / "node_modules" / "foo" / "package.json", '{"name": "foo"}\n')
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        for module in data["modules"]:
            assert "node_modules" not in module["path"].replace("\\", "/")

    def test_detects_codeowners(self, tmp_path: Path, monkeypatch: object) -> None:
        """Parses a CODEOWNERS file when present."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(
            tmp_path / "CODEOWNERS",
            "# CODEOWNERS\nsrc/ @team-backend\n*.md @team-docs @alice\n",
        )
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        entries = data["codeowners"]
        patterns = {e["pattern"] for e in entries}
        assert "src/" in patterns
        assert "*.md" in patterns
        md_entry = next(e for e in entries if e["pattern"] == "*.md")
        assert "@team-docs" in md_entry["owners"]
        assert "@alice" in md_entry["owners"]

    def test_detects_generated_file_via_header(self, tmp_path: Path, monkeypatch: object) -> None:
        """Flags a file whose first lines say 'DO NOT EDIT' or '@generated'."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        _write(
            tmp_path / "gen" / "api_pb2.py",
            "# @generated by protoc. DO NOT EDIT.\n\nclass _Example: ...\n",
        )
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads((tmp_path / ".ces" / "brownfield" / "scan.json").read_text(encoding="utf-8"))
        generated = [g.replace("\\", "/") for g in data["generated_files"]]
        assert any("gen/api_pb2.py" in g for g in generated)

    def test_re_running_overwrites_prior_scan(self, tmp_path: Path, monkeypatch: object) -> None:
        """Re-running ces scan replaces the previous scan.json content."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        out = tmp_path / ".ces" / "brownfield" / "scan.json"
        out.parent.mkdir(parents=True)
        (tmp_path / ".ces" / "config.yaml").write_text("project_id: proj-test\n", encoding="utf-8")
        out.write_text('{"stale": true}', encoding="utf-8")
        _write(tmp_path / "pyproject.toml", '[project]\nname = "x"\n')
        app = _get_app()
        runner.invoke(app, ["scan"])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "stale" not in data
