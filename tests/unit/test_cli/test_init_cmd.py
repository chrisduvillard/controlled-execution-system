"""Tests for ces init command (init_cmd module)."""

from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


class TestCesInit:
    """Tests for the ces init command."""

    def test_creates_ces_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init creates a .ces/ directory in the current working directory."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert (tmp_path / ".ces").is_dir(), f"stdout={result.stdout}, exit={result.exit_code}"

    def test_creates_config_yaml(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init creates .ces/config.yaml with project name."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        config_path = tmp_path / ".ces" / "config.yaml"
        assert config_path.exists(), f"stdout={result.stdout}"
        content = config_path.read_text()
        assert "myproject" in content

    def test_creates_keys_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init creates .ces/keys/ directory for Ed25519 keypair."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "myproject"])
        assert (tmp_path / ".ces" / "keys").is_dir()

    def test_creates_artifacts_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init creates .ces/artifacts/ directory for draft truth artifacts."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "myproject"])
        assert (tmp_path / ".ces" / "artifacts").is_dir()

    def test_errors_if_already_initialized(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init shows error and exits 1 if .ces/ already exists."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        (tmp_path / ".ces").mkdir()
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code != 0

    def test_init_upgrades_profile_only_ces_directory(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces profile detect --write` before init must not strand projects without keys."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        detect = runner.invoke(app, ["profile", "detect", "--write"])
        assert detect.exit_code == 0, detect.stdout
        profile_path = tmp_path / ".ces" / "verification-profile.json"
        assert profile_path.is_file()

        result = runner.invoke(app, ["init", "myproject"])

        assert result.exit_code == 0, result.stdout
        assert profile_path.is_file()
        assert (tmp_path / ".ces" / "config.yaml").is_file()
        assert (tmp_path / ".ces" / "keys" / "ed25519_private.key").is_file()
        assert (tmp_path / ".ces" / "state.db").is_file()

    def test_init_project_root_upgrades_profile_only_target_not_cwd(self, tmp_path: Path, monkeypatch: object) -> None:
        """Source-checkout invocations can initialize a target after profile detection."""
        source_checkout = tmp_path / "ces-source"
        target_repo = tmp_path / "target-repo"
        source_checkout.mkdir()
        profile_path = target_repo / ".ces" / "verification-profile.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text('{"version": 1, "checks": {}}', encoding="utf-8")
        monkeypatch.chdir(source_checkout)  # type: ignore[attr-defined]
        app = _get_app()

        result = runner.invoke(app, ["init", "--project-root", str(target_repo), "myproject", "--yes"])

        assert result.exit_code == 0, result.stdout
        assert not (source_checkout / ".ces").exists()
        assert profile_path.is_file()
        assert (target_repo / ".ces" / "config.yaml").is_file()
        assert (target_repo / ".ces" / "keys" / "ed25519_private.key").is_file()

    def test_init_refuses_profile_directory_with_extra_state(self, tmp_path: Path, monkeypatch: object) -> None:
        """Only a profile-only .ces/ directory is safe to upgrade in place."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        ces_dir = tmp_path / ".ces"
        ces_dir.mkdir()
        (ces_dir / "verification-profile.json").write_text('{"version": 1, "checks": {}}', encoding="utf-8")
        (ces_dir / "custom.json").write_text("{}", encoding="utf-8")
        app = _get_app()

        result = runner.invoke(app, ["init", "myproject"])

        assert result.exit_code != 0
        assert not (tmp_path / ".ces" / "keys").exists()
        assert not (tmp_path / ".ces" / "config.yaml").exists()

    def test_init_rejects_symlinked_ces_dir_even_with_profile_bootstrap(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """Profile bootstrap must not make init follow .ces symlinks outside the project."""
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "verification-profile.json").write_text('{"version": 1, "checks": {}}', encoding="utf-8")
        (project / ".ces").symlink_to(outside, target_is_directory=True)
        monkeypatch.chdir(project)  # type: ignore[attr-defined]
        app = _get_app()

        result = runner.invoke(app, ["init", "myproject"])

        assert result.exit_code != 0
        assert "symlink" in result.stdout.lower() or "symlink" in str(result.exception).lower()
        assert not (outside / "keys").exists()
        assert not (outside / "config.yaml").exists()

    def test_displays_success_message(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init displays a success message mentioning the project name."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code == 0
        assert "myproject" in result.stdout or "Initialized" in result.stdout

    def test_success_message_points_to_build_command(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init recommends the builder-first `ces build` entrypoint."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code == 0
        assert 'ces build "describe what you want to build"' in result.stdout

    def test_init_without_name_defaults_to_directory_name(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init with no NAME derives a safe project name from cwd."""
        project_dir = tmp_path / "my cool.repo"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0, result.stdout
        import yaml

        config = yaml.safe_load((project_dir / ".ces" / "config.yaml").read_text())
        assert config["project_name"] == "my-cool.repo"

    def test_init_project_root_initializes_requested_directory_not_cwd(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """--project-root prevents source-checkout invocations from initializing cwd by accident."""
        source_checkout = tmp_path / "ces-source"
        target_repo = tmp_path / "target repo"
        source_checkout.mkdir()
        target_repo.mkdir()
        monkeypatch.chdir(source_checkout)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "--project-root", str(target_repo)])
        assert result.exit_code == 0, result.stdout
        assert (target_repo / ".ces").is_dir()
        assert not (source_checkout / ".ces").exists()
        import yaml

        config = yaml.safe_load((target_repo / ".ces" / "config.yaml").read_text())
        assert config["project_name"] == "target-repo"

    def test_init_success_message_reflects_detected_runtime(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init should not tell users to install runtimes already found on PATH."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name == "codex" else None)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code == 0, result.stdout
        assert "Detected Codex CLI" in result.stdout
        assert "Install/authenticate" not in result.stdout
        assert "ces doctor" in result.stdout
        assert "--verify-runtime" in result.stdout

    def test_init_accepts_yes_for_automation_consistency(self, tmp_path: Path, monkeypatch: object) -> None:
        """RunLens dogfood: `ces init --project-root ... --yes` should be accepted."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        target = tmp_path / "runlens"
        target.mkdir()
        app = _get_app()
        result = runner.invoke(app, ["init", "--project-root", str(target), "--yes"])
        assert result.exit_code == 0, result.stdout
        assert (target / ".ces" / "config.yaml").exists()

    def test_init_ignores_ces_state_and_common_local_artifacts(self, tmp_path: Path, monkeypatch: object) -> None:
        """RunLens dogfood: init should prevent accidental `git add .` of CES secrets/state."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject", "--yes"])
        assert result.exit_code == 0, result.stdout
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        for entry in (".ces/", ".venv/", ".coverage", "coverage.json", "*.egg-info/", "dist/", "build/"):
            assert entry in gitignore
        assert (tmp_path / ".ces" / ".gitignore").read_text(encoding="utf-8").strip() == "*"

    def test_validates_project_name(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init rejects project names with path traversal characters."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "../evil"])
        assert result.exit_code != 0

    def test_rejects_leading_dot_name(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init rejects names starting with a dot (T-06-01 mitigation)."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", ".hidden"])
        assert result.exit_code != 0

    def test_rejects_name_with_slash(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init rejects names containing slashes."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "foo/bar"])
        assert result.exit_code != 0

    def test_accepts_name_with_dots_hyphens_underscores(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init accepts names with dots, hyphens, and underscores after first char."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "my-project_v1.0"])
        assert result.exit_code == 0
        assert (tmp_path / ".ces").is_dir()

    def test_config_yaml_contains_version(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init writes version field into config.yaml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "testproj"])
        import yaml

        config_path = tmp_path / ".ces" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert "version" in config
        assert config["project_name"] == "testproj"

    def test_config_yaml_contains_created_at(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init writes created_at timestamp into config.yaml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "testproj"])
        import yaml

        config_path = tmp_path / ".ces" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        assert "created_at" in config

    def test_creates_local_state_db(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init creates .ces/state.db for local-first persistence."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code == 0
        assert (tmp_path / ".ces" / "state.db").is_file()

    def test_config_defaults_to_local_runtime_preferences(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces init writes local-first runtime settings into config.yaml."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "testproj"])
        import yaml

        config_path = tmp_path / ".ces" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        from ces import __version__

        assert config["execution_mode"] == "local"
        assert config["preferred_runtime"] is None
        assert config["version"] == __version__


class TestCesInitPersistsKeys:
    """ces init must persist the Ed25519 keypair and audit HMAC secret (B1/B2 regression)."""

    def test_creates_ed25519_private_key_file(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["init", "myproject"])
        assert result.exit_code == 0, result.stdout
        key = tmp_path / ".ces" / "keys" / "ed25519_private.key"
        assert key.is_file()
        assert len(key.read_bytes()) == 32

    def test_creates_ed25519_public_key_file(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "myproject"])
        key = tmp_path / ".ces" / "keys" / "ed25519_public.key"
        assert key.is_file()
        assert len(key.read_bytes()) == 32

    def test_creates_audit_hmac_secret(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "myproject"])
        secret = tmp_path / ".ces" / "keys" / "audit.hmac"
        assert secret.is_file()
        assert len(secret.read_bytes()) == 32  # AUDIT_HMAC_SECRET_BYTES

    def test_persisted_keys_verify_signed_content(self, tmp_path: Path, monkeypatch: object) -> None:
        """Keys written by `ces init` must actually round-trip sign/verify."""
        from ces.shared.crypto import sign_content, verify_signature

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        runner.invoke(app, ["init", "myproject"])
        priv = (tmp_path / ".ces" / "keys" / "ed25519_private.key").read_bytes()
        pub = (tmp_path / ".ces" / "keys" / "ed25519_public.key").read_bytes()
        signature = sign_content(b"probe", priv)
        assert verify_signature(b"probe", signature, pub) is True

    def test_two_separate_inits_produce_different_keys(self, tmp_path: Path, monkeypatch: object) -> None:
        """Each project gets its own keypair; secrets should never collide across projects."""
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        app = _get_app()

        monkeypatch.chdir(a)  # type: ignore[attr-defined]
        runner.invoke(app, ["init", "proja"])
        priv_a = (a / ".ces" / "keys" / "ed25519_private.key").read_bytes()

        monkeypatch.chdir(b)  # type: ignore[attr-defined]
        runner.invoke(app, ["init", "projb"])
        priv_b = (b / ".ces" / "keys" / "ed25519_private.key").read_bytes()

        assert priv_a != priv_b


class TestCesAppStructure:
    """Tests for the CLI app structure."""

    def test_app_is_typer_instance(self) -> None:
        """The app object is a Typer instance."""
        import typer

        app = _get_app()
        assert isinstance(app, typer.Typer)

    def test_app_has_init_command(self) -> None:
        """The app has an init command registered."""
        app = _get_app()
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "init" in result.stdout.lower() or "project" in result.stdout.lower()

    def test_root_help_highlights_start_here_and_advanced_governance(self) -> None:
        """The root help steers users to builder-first commands before expert commands."""
        app = _get_app()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Start Here" in result.stdout
        assert "Advanced Governance" in result.stdout
        assert "build" in result.stdout
        assert "continue" in result.stdout
