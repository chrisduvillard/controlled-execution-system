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

    def test_python_requirement_rejects_python_314(self, tmp_path: Path, monkeypatch: object) -> None:
        """Doctor should mirror package metadata: Python 3.12/3.13 only."""
        import shutil
        from types import SimpleNamespace

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            "ces.cli.doctor_cmd.sys.version_info",
            SimpleNamespace(major=3, minor=14, micro=0),
        )

        app = _get_app()
        result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1
        assert "Python >= 3.12,<3.14" in result.stdout
        assert "3.14.0" in result.stdout

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

    def test_installed_runtime_is_labeled_auth_unverified_by_default(self, tmp_path: Path, monkeypatch: object) -> None:
        """PATH-only doctor checks must not imply runtime auth/entitlement is verified."""
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.delenv("CES_DEMO_MODE", raising=False)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "auth not verified" in result.stdout.lower()

    def test_json_doctor_exposes_runtime_auth_state(self, tmp_path: Path, monkeypatch: object) -> None:
        """JSON doctor distinguishes installed runtimes from auth-verified runtimes."""
        import json
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["--json", "doctor"])
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["runtime_auth"]["codex"]["installed"] is True
        assert payload["runtime_auth"]["codex"]["auth_checked"] is False
        assert payload["runtime_auth"]["codex"]["auth_ok"] is None

    def test_doctor_project_root_json_checks_target_project_from_orchestrator_cwd(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """ReleasePulse RP-CES-001: doctor supports --project-root like adjacent commands."""
        import json
        import shutil

        orchestrator = tmp_path / "orchestrator"
        target = tmp_path / "target-project"
        orchestrator.mkdir()
        (target / ".ces").mkdir(parents=True)
        (target / ".ces" / "config.yaml").write_text("project_id: releasepulse\n", encoding="utf-8")
        (target / "pyproject.toml").write_text("[project]\nname = 'releasepulse'\n", encoding="utf-8")
        (target / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        monkeypatch.chdir(orchestrator)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)  # type: ignore[attr-defined]

        app = _get_app()
        result = runner.invoke(app, ["doctor", "--project-root", str(target), "--json"])

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["project_root"] == str(target.resolve())
        assert payload["project_dir"] == {"exists": True, "path": str(target.resolve() / ".ces")}
        assert payload["dependency_freshness"]["dependency lockfile"]["ok"] is True

    def test_doctor_project_root_verify_runtime_probe_uses_target_cwd(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """ReleasePulse RP-CES-001: --verify-runtime probes from the explicit project root."""
        import json
        import shutil

        target = tmp_path / "target-project"
        (target / ".ces").mkdir(parents=True)
        (target / ".ces" / "config.yaml").write_text("project_id: releasepulse\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)  # type: ignore[attr-defined]

        seen_cwd: list[Path] = []

        def fake_probe(runtime: str, executable: str, cwd: Path) -> tuple[bool, str]:
            del runtime, executable
            seen_cwd.append(cwd)
            return True, f"cwd={cwd}"

        monkeypatch.setattr("ces.cli.doctor_cmd._probe_runtime_auth", fake_probe)
        app = _get_app()
        result = runner.invoke(
            app,
            ["doctor", "--project-root", str(target), "--verify-runtime", "--runtime", "codex", "--json"],
        )

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert seen_cwd == [target.resolve()]
        assert payload["runtime_auth"]["codex"]["detail"] == f"cwd={target.resolve()}"

    def test_doctor_verify_runtime_option_marks_auth_checked(self, tmp_path: Path, monkeypatch: object) -> None:
        """RunLens dogfood: init guidance command `ces doctor --verify-runtime` must exist."""
        import json
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            "ces.cli.doctor_cmd._probe_runtime_auth",
            lambda runtime, executable, cwd: (True, f"{runtime} auth probe succeeded"),
        )
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--verify-runtime", "--json"])
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["runtime_auth"]["codex"]["auth_checked"] is True
        assert payload["runtime_auth"]["codex"]["auth_ok"] is True
        assert "auth probe succeeded" in payload["runtime_auth"]["codex"]["detail"]

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
        assert "no optional runtime extras" in result.stdout

    def test_default_doctor_hides_optional_compat_extras(self, tmp_path: Path, monkeypatch: object) -> None:
        """Default doctor keeps optional extras out of the local-first path."""
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        app = _get_app()
        result = runner.invoke(app, ["doctor"])
        assert "no optional runtime extras" not in result.stdout

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

    def test_doctor_verify_runtime_can_target_one_runtime(self, tmp_path: Path, monkeypatch: object) -> None:
        """SpecTrail SF-001: one broken installed runtime should not fail a targeted probe."""
        import json
        import shutil

        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None,
        )  # type: ignore[attr-defined]

        def fake_probe(runtime: str, executable: str, cwd: Path) -> tuple[bool, str]:
            if runtime == "codex":
                return True, "codex auth probe succeeded"
            return False, "claude auth probe failed"

        monkeypatch.setattr("ces.cli.doctor_cmd._probe_runtime_auth", fake_probe)
        app = _get_app()
        result = runner.invoke(app, ["doctor", "--verify-runtime", "--runtime", "codex", "--json"])
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["runtime_filter"] == "codex"
        assert payload["runtime_auth"]["codex"]["auth_checked"] is True
        assert payload["runtime_auth"]["claude"]["auth_checked"] is False

    def test_runtime_auth_failure_detail_includes_actionable_stderr(self, monkeypatch: object, tmp_path: Path) -> None:
        """SpecTrail SF-002: auth probe failures include runtime, exit code, and stderr tail."""
        import subprocess

        class Completed:
            returncode = 42
            stdout = ""
            stderr = "not logged in: run codex login"

        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Completed())
        ok, detail = __import__("ces.cli.doctor_cmd", fromlist=["_probe_runtime_auth"])._probe_runtime_auth(
            "codex", "/usr/bin/codex", tmp_path
        )
        assert ok is False
        assert "runtime=codex" in detail
        assert "exit_code=42" in detail
        assert "codex login" in detail


def test_runtime_auth_success_detail_includes_actionable_probe_metadata(tmp_path: Path, monkeypatch: object) -> None:
    """PromptVault dogfood: successful auth probe should still identify runtime/command/exit/output."""
    from ces.cli.doctor_cmd import _probe_runtime_auth

    class Completed:
        returncode = 0
        stdout = "READY\n"
        stderr = ""

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        assert command[:2] == ["/usr/bin/codex", "exec"]
        return Completed()

    monkeypatch.setattr("ces.cli.doctor_cmd.subprocess.run", fake_run)  # type: ignore[attr-defined]

    ok, detail = _probe_runtime_auth("codex", "/usr/bin/codex", tmp_path)

    assert ok is True
    assert "runtime=codex" in detail
    assert "command=codex exec" in detail
    assert "exit_code=0" in detail
    assert "stdout_tail=READY" in detail
