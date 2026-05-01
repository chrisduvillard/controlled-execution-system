"""Tests for ces doctor command (doctor_cmd module)."""

from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


class TestCesDoctor:
    """Tests for the ces doctor command."""

    def test_doctor_command_is_registered(self) -> None:
        """The app has a doctor command registered."""
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0

    def test_reports_python_version(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor shows the current Python version in its output."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert "Python" in result.stdout
        assert f"{sys.version_info.major}.{sys.version_info.minor}" in result.stdout

    def test_reports_provider_checks(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor shows provider availability checks."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.delenv("CES_DEMO_MODE", raising=False)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert "CES_DEMO_MODE" in result.stdout
        assert "claude" in result.stdout.lower()
        assert "codex" in result.stdout.lower()

    def test_reports_demo_mode_when_set(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor reports CES_DEMO_MODE=1 but still requires a local runtime."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setenv("CES_DEMO_MODE", "1")  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda _name: None)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert "CES_DEMO_MODE" in result.stdout
        assert result.exit_code == 1

    def test_runtime_alone_is_enough_for_build_readiness(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor returns 0 when a supported local runtime is available."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.delenv("CES_DEMO_MODE", raising=False)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/codex" if name == "codex" else None,
        )  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "codex CLI" in result.stdout
        assert "on PATH" in result.stdout

    def test_exits_nonzero_when_no_provider(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor exits non-zero when no provider is available and no demo mode."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.delenv("CES_DEMO_MODE", raising=False)  # type: ignore[attr-defined]
        # Stub shutil.which so neither CLI appears available.
        monkeypatch.setattr(shutil, "which", lambda _name: None)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code != 0

    def test_reports_extras_status_in_expert_mode(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor --expert reports install state of each optional extras group."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--expert"])
        # Should name the optional extras groups explicitly.
        assert "docker" in result.stdout

    def test_default_doctor_hides_optional_compat_extras(self, tmp_path: Path, monkeypatch: object) -> None:
        """Default doctor keeps Docker out of the local-first path."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert "Extras: docker" not in result.stdout

    def test_reports_ces_directory_status(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces doctor mentions whether a .ces/ project directory exists."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        # No .ces/ here — doctor should say so in its output.
        result = runner.invoke(app, ["doctor"])
        assert ".ces" in result.stdout

    def test_json_output_is_parseable(self, tmp_path: Path, monkeypatch: object) -> None:
        """ces --json doctor emits parseable JSON to stdout."""
        import json
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setenv("CES_DEMO_MODE", "1")  # type: ignore[attr-defined]
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/codex" if name == "codex" else None,
        )  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor"])
        # Either a trailing JSON doc or an all-JSON doc is acceptable.
        # Find the first '{' and parse from there.
        idx = result.stdout.find("{")
        assert idx != -1, f"no JSON in output: {result.stdout}"
        payload = json.loads(result.stdout[idx:])
        assert "python_version" in payload
        assert "providers" in payload
        assert "runtime_available" in payload
        assert "extras" in payload
        assert "runtime_safety" in payload
        assert payload["runtime_safety"]["codex"]["tool_allowlist_enforced"] is False

    def test_strict_providers_passes_when_threshold_met(self, tmp_path: Path, monkeypatch: object) -> None:
        """``--strict-providers 1`` passes when a single CLI runtime is on PATH."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setenv("CES_DEMO_MODE", "1")  # type: ignore[attr-defined]
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--strict-providers", "1"])
        assert "Distinct providers >= 1" in result.stdout

    def test_strict_providers_fails_when_threshold_unmet(self, tmp_path: Path, monkeypatch: object) -> None:
        """``--strict-providers 5`` fails when only 1-2 providers register."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setenv("CES_DEMO_MODE", "1")  # type: ignore[attr-defined]
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--strict-providers", "5"])
        assert result.exit_code != 0
        assert "Tier-A diversity" in result.stdout

    def test_plain_doctor_resets_json_mode_after_json_invocation(self, tmp_path: Path, monkeypatch: object) -> None:
        """A prior --json command must not force later doctor runs into JSON mode."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda _name: None)  # type: ignore[attr-defined]
        app = _get_app()

        json_result = runner.invoke(app, ["--json", "doctor"])
        assert json_result.exit_code != 0
        assert json_result.stdout.lstrip().startswith("{")

        rich_result = runner.invoke(app, ["doctor"])
        assert rich_result.exit_code != 0
        assert "Python" in rich_result.stdout


class TestCesDoctorSecurity:
    """`ces doctor --security` runs posture checks for 0.1.2+ key material."""

    def _init_project(self, project_dir: Path) -> None:
        """Run the real initializer to lay down .ces/keys/ + state.db."""
        from ces.cli.init_cmd import initialize_local_project

        initialize_local_project(project_dir, name="sectest")

    def test_reports_all_green_for_fresh_init(self, tmp_path: Path, monkeypatch: object) -> None:
        """Immediately after `ces init`, every security check passes."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        self._init_project(tmp_path)
        monkeypatch.delenv("CES_AUDIT_HMAC_SECRET", raising=False)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor", "--security"])
        assert result.exit_code == 0, result.stdout

        import json as _json

        payload = _json.loads(result.stdout)
        assert payload["security_ok"] is True
        assert all(check["ok"] for check in payload["security"].values())

    def test_fails_when_keys_dir_missing(self, tmp_path: Path, monkeypatch: object) -> None:
        """Missing .ces/keys/ → non-zero exit + failing security section."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        # No `ces init` — .ces/keys/ doesn't exist.
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor", "--security"])
        assert result.exit_code == 1

        import json as _json

        payload = _json.loads(result.stdout)
        assert payload["security_ok"] is False
        assert payload["security"][".ces/keys/ permissions"]["ok"] is False

    def test_fails_when_ces_parent_dir_is_not_private(self, tmp_path: Path, monkeypatch: object) -> None:
        """World-traversable .ces/ must fail the security posture check."""
        import json as _json
        import os
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        self._init_project(tmp_path)
        os.chmod(tmp_path / ".ces", 0o755)  # noqa: S103 - deliberately insecure for doctor check
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor", "--security"])

        payload = _json.loads(result.stdout)
        assert result.exit_code == 1
        assert payload["security"][".ces/ permissions"]["ok"] is False

    def test_fails_when_hmac_env_is_dev_default(self, tmp_path: Path, monkeypatch: object) -> None:
        """Setting CES_AUDIT_HMAC_SECRET to the dev marker must trip the check."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        self._init_project(tmp_path)
        monkeypatch.setenv(  # type: ignore[attr-defined]
            "CES_AUDIT_HMAC_SECRET", "ces-dev-hmac-secret-do-not-use-in-production"
        )
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor", "--security"])
        assert result.exit_code == 1

        import json as _json

        payload = _json.loads(result.stdout)
        assert payload["security"]["CES_AUDIT_HMAC_SECRET env"]["ok"] is False

    def test_accepts_custom_hmac_env_override(self, tmp_path: Path, monkeypatch: object) -> None:
        """A non-default CES_AUDIT_HMAC_SECRET passes the env check."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        self._init_project(tmp_path)
        monkeypatch.setenv(  # type: ignore[attr-defined]
            "CES_AUDIT_HMAC_SECRET", "some-32-byte-random-secret-value-xxx"
        )
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor", "--security"])
        assert result.exit_code == 0, result.stdout

        import json as _json

        payload = _json.loads(result.stdout)
        assert payload["security"]["CES_AUDIT_HMAC_SECRET env"]["ok"] is True

    def test_without_security_flag_unchanged(self, tmp_path: Path, monkeypatch: object) -> None:
        """`ces doctor` without --security does NOT include security section."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(  # type: ignore[attr-defined]
            shutil, "which", lambda name: f"/usr/bin/{name}"
        )
        # No .ces/ at all. Without --security, exit code is driven only by
        # Python + runtime availability, both of which are OK here.
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor"])
        assert result.exit_code == 0, result.stdout

        import json as _json

        payload = _json.loads(result.stdout)
        assert "security" not in payload
        assert "security_ok" not in payload

    def test_non_security_failure_still_dominates(self, tmp_path: Path, monkeypatch: object) -> None:
        """Security section alone doesn't rescue a missing runtime."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        # No runtime on PATH.
        monkeypatch.setattr(shutil, "which", lambda _name: None)  # type: ignore[attr-defined]
        self._init_project(tmp_path)
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--security"])
        assert result.exit_code == 1  # runtime missing, not a security issue
