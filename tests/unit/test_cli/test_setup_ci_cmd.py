"""Tests for ces setup-ci command (setup_ci_cmd module)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    from ces.cli import app

    return app


class TestCesSetupCi:
    """Tests for the ces setup-ci command."""

    def test_setup_ci_is_registered(self) -> None:
        """The app has a setup-ci command registered."""
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--help"])
        assert result.exit_code == 0

    def test_github_workflow_is_written(self, tmp_path: Path, monkeypatch: object) -> None:
        """--provider github writes .github/workflows/ces-gating.yml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github"])
        assert result.exit_code == 0, result.stdout
        target = tmp_path / ".github" / "workflows" / "ces-gating.yml"
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "name:" in content
        # Workflow should run CES gating commands on pull_request events.
        assert "pull_request" in content
        assert "ces" in content.lower()

    def test_gitlab_file_is_written(self, tmp_path: Path, monkeypatch: object) -> None:
        """--provider gitlab writes .gitlab-ci.yml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "gitlab"])
        assert result.exit_code == 0, result.stdout
        target = tmp_path / ".gitlab-ci.yml"
        assert target.is_file()
        content = target.read_text(encoding="utf-8")
        assert "ces" in content.lower()

    def test_refuses_to_overwrite_existing_file(self, tmp_path: Path, monkeypatch: object) -> None:
        """Refuses to clobber an existing workflow unless --force is passed."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        target = tmp_path / ".github" / "workflows" / "ces-gating.yml"
        target.parent.mkdir(parents=True)
        target.write_text("# existing workflow\n", encoding="utf-8")
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github"])
        assert result.exit_code != 0
        # Original content must be preserved.
        assert target.read_text(encoding="utf-8") == "# existing workflow\n"

    def test_force_flag_overwrites_existing(self, tmp_path: Path, monkeypatch: object) -> None:
        """--force overwrites an existing workflow file."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        target = tmp_path / ".github" / "workflows" / "ces-gating.yml"
        target.parent.mkdir(parents=True)
        target.write_text("# existing\n", encoding="utf-8")
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github", "--force"])
        assert result.exit_code == 0, result.stdout
        assert target.read_text(encoding="utf-8") != "# existing\n"

    def test_project_root_writes_workflow_outside_cwd(self, tmp_path: Path, monkeypatch: object) -> None:
        """--project-root writes the workflow into the requested repository root."""
        repo = tmp_path / "repo"
        outside = tmp_path / "outside"
        repo.mkdir()
        outside.mkdir()
        monkeypatch.chdir(outside)  # type: ignore[attr-defined]

        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github", "--project-root", str(repo)])

        assert result.exit_code == 0, result.stdout
        assert (repo / ".github" / "workflows" / "ces-gating.yml").is_file()
        assert not (outside / ".github").exists()

    def test_refuses_project_root_workflow_symlink_escape(self, tmp_path: Path, monkeypatch: object) -> None:
        """CI setup must not write workflow files through symlinked repo paths."""
        repo = tmp_path / "repo"
        outside = tmp_path / "outside"
        repo.mkdir()
        outside.mkdir()
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        (repo / ".github").symlink_to(outside, target_is_directory=True)

        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github", "--project-root", str(repo), "--force"])

        assert result.exit_code != 0
        assert "unsafe CI workflow path" in f"{result.stdout}\n{result.stderr}\n{result.exception}"
        assert not (outside / "workflows" / "ces-gating.yml").exists()

    def test_force_replaces_workflow_hardlink_without_clobbering_external_file(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """--force replaces a hardlinked workflow target instead of overwriting its linked peer."""
        repo = tmp_path / "repo"
        outside = tmp_path / "outside"
        target = repo / ".github" / "workflows" / "ces-gating.yml"
        external = outside / "shared-workflow.yml"
        target.parent.mkdir(parents=True)
        outside.mkdir()
        external.write_text("# external sentinel\n", encoding="utf-8")
        try:
            os.link(external, target)
        except OSError as exc:
            pytest.skip(f"hardlinks unavailable on this filesystem: {exc}")
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]

        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "github", "--project-root", str(repo), "--force"])

        assert result.exit_code == 0, result.stdout
        assert external.read_text(encoding="utf-8") == "# external sentinel\n"
        assert target.read_text(encoding="utf-8") != external.read_text(encoding="utf-8")
        assert target.stat().st_ino != external.stat().st_ino

    def test_invalid_provider_rejected(self, tmp_path: Path, monkeypatch: object) -> None:
        """An unknown provider value exits non-zero."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["setup-ci", "--provider", "bitbucket"])
        assert result.exit_code != 0
