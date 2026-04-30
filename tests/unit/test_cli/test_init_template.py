"""Tests for the ces init --template flag."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


class TestCesInitTemplate:
    """Tests for the --template option of ces init."""

    def test_template_flag_is_available(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces init --help` lists the --template option."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        # NO_COLOR + wide terminal so Rich renders plain help that survives
        # a simple substring check in CI (headless runner changes Rich's
        # default panel width and wraps ``--template`` across lines).
        result = runner.invoke(
            app,
            ["init", "--help"],
            env={"COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb"},
        )
        assert result.exit_code == 0
        assert "--template" in result.stdout

    def test_python_service_template_is_written(self, tmp_path: Path, monkeypatch: object) -> None:
        """--template python-service drops a starter manifest into .ces/artifacts/."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproj", "--template", "python-service"])
        assert result.exit_code == 0, result.stdout
        target = tmp_path / ".ces" / "artifacts" / "manifest-template.yaml"
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        # Starter manifest should at least define a human-facing description.
        assert "description" in content.lower()

    def test_python_library_template_is_written(self, tmp_path: Path, monkeypatch: object) -> None:
        """--template python-library works too."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "mylib", "--template", "python-library"])
        assert result.exit_code == 0, result.stdout
        target = tmp_path / ".ces" / "artifacts" / "manifest-template.yaml"
        assert target.is_file()

    def test_unknown_template_rejected(self, tmp_path: Path, monkeypatch: object) -> None:
        """An unknown template name exits non-zero and does not create .ces/."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproj", "--template", "rust-service"])
        assert result.exit_code != 0
        # Must not have partially bootstrapped the project.
        assert not (tmp_path / ".ces").exists()

    def test_init_without_template_still_works(self, tmp_path: Path, monkeypatch: object) -> None:
        """Calling `ces init` without --template retains the prior behaviour."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproj"])
        assert result.exit_code == 0
        assert (tmp_path / ".ces").is_dir()
        # No template file when --template wasn't passed.
        assert not (tmp_path / ".ces" / "artifacts" / "manifest-template.yaml").exists()
