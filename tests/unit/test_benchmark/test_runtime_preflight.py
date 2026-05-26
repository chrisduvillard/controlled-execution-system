"""Unit coverage for benchmark runtime preflight checks."""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

from ces.benchmark.runtime_preflight import (
    _TIMEOUT_EXIT_CODE,
    _probe_command,
    _probe_file_status,
    _ProbeResult,
    _process_group_has_live_members,
    _read_limited_file,
    _run_probe_command,
    _runtime_env,
    _safe_tail,
    _safe_unlink_probe,
    run_runtime_preflight,
)


def test_runtime_preflight_without_probe_marks_runtime_not_verified_without_creating_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")
    project_root = tmp_path / "not-yet-created"

    payload = run_runtime_preflight(runtime="codex", project_root=project_root, probe_runtime=False)

    assert payload["recommendation"] == "runtime-not-verified"
    assert payload["installed"] is True
    assert payload["checks"][1]["name"] == "workspace-write-probe"
    assert payload["checks"][1]["ok"] is None
    assert not project_root.exists()


def test_runtime_preflight_reports_missing_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda _name: None)

    payload = run_runtime_preflight(runtime="claude", project_root=tmp_path, probe_runtime=True)

    assert payload["recommendation"] == "runtime-missing"
    assert payload["installed"] is False
    assert payload["checks"][0]["ok"] is False
    assert payload["checks"][1]["detail"] == "skipped because runtime is missing"


def test_runtime_preflight_reports_codex_write_probe_blocker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_probe(_command, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["cwd"] == tmp_path
        assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"]
        return _ProbeResult(
            exit_code=0,
            stdout_tail="agent finished without writing file",
            stderr_tail="bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted",
        )

    monkeypatch.setattr("ces.benchmark.runtime_preflight._run_probe_command", fake_probe)

    payload = run_runtime_preflight(runtime="codex", project_root=tmp_path, probe_runtime=True)

    assert payload["recommendation"] == "runtime-blocked"
    probe = payload["checks"][1]
    assert probe["name"] == "workspace-write-probe"
    assert probe["ok"] is False
    assert probe["exit_code"] == 0
    assert "without creating benchmark probe file" in probe["detail"]
    assert "RTM_NEWADDR" in probe["stderr_tail"]


def test_runtime_preflight_reports_ready_when_probe_file_exists(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_probe(_command, **kwargs):  # type: ignore[no-untyped-def]
        cwd = Path(kwargs["cwd"])
        (cwd / ".ces-benchmark-runtime-probe.txt").write_text("ces-benchmark-runtime-ready", encoding="utf-8")
        return _ProbeResult(exit_code=0, stdout_tail="done", stderr_tail="")

    monkeypatch.setattr("ces.benchmark.runtime_preflight._run_probe_command", fake_probe)

    payload = run_runtime_preflight(runtime="claude", project_root=tmp_path, probe_runtime=True)

    assert payload["recommendation"] == "runtime-ready"
    assert payload["checks"][1]["ok"] is True
    assert not (tmp_path / ".ces-benchmark-runtime-probe.txt").exists()


def test_runtime_preflight_reports_timeout_detail(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_probe(_command, **_kwargs):  # type: ignore[no-untyped-def]
        return _ProbeResult(exit_code=_TIMEOUT_EXIT_CODE, stdout_tail="", stderr_tail="", timed_out=True)

    monkeypatch.setattr("ces.benchmark.runtime_preflight._run_probe_command", fake_probe)

    payload = run_runtime_preflight(runtime="codex", project_root=tmp_path, probe_runtime=True, timeout_seconds=7)

    assert payload["recommendation"] == "runtime-blocked"
    assert payload["checks"][1]["detail"] == "runtime probe timed out after 7s"


def test_probe_file_status_rejects_missing_unexpected_and_symlink(tmp_path: Path) -> None:
    missing_ok, missing_detail = _probe_file_status(tmp_path / "missing.txt")
    assert missing_ok is False
    assert "without creating" in missing_detail

    unexpected = tmp_path / "probe.txt"
    unexpected.write_text("wrong", encoding="utf-8")
    unexpected_ok, unexpected_detail = _probe_file_status(unexpected)
    assert unexpected_ok is False
    assert "unexpected probe content" in unexpected_detail

    outside = tmp_path / "outside.txt"
    outside.write_text("ces-benchmark-runtime-ready", encoding="utf-8")
    symlink = tmp_path / "probe-link.txt"
    symlink.symlink_to(outside)
    symlink_ok, symlink_detail = _probe_file_status(symlink)
    assert symlink_ok is False
    assert "symlinked" in symlink_detail


def test_safe_unlink_probe_leaves_symlink_target_intact(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("safe", encoding="utf-8")
    symlink = tmp_path / ".ces-benchmark-runtime-probe.txt"
    symlink.symlink_to(outside)

    _safe_unlink_probe(symlink)

    assert symlink.exists()
    assert outside.read_text(encoding="utf-8") == "safe"


def test_read_limited_file_handles_file_like_and_non_file_like() -> None:
    assert _read_limited_file(object()) == b""
    text_handle = io.StringIO("x" * 700)
    assert _read_limited_file(text_handle) == b"x" * 500


def test_run_probe_command_reports_launch_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_popen(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError("boom")

    monkeypatch.setattr("ces.benchmark.runtime_preflight.subprocess.Popen", fake_popen)

    result = _run_probe_command(["missing-runtime"], cwd=tmp_path, env={}, timeout_seconds=1)

    assert result.exit_code is None
    assert "failed before launch" in result.stderr_tail


def test_run_probe_command_success_captures_sanitized_streams(tmp_path: Path) -> None:
    script = "import sys; print('ok'); print('session id: 12345678-1234-1234-1234-123456789abc', file=sys.stderr)"

    result = _run_probe_command([sys.executable, "-c", script], cwd=tmp_path, env=os.environ, timeout_seconds=5)

    assert result.exit_code == 0
    assert result.stdout_tail == "ok"
    assert "12345678" not in result.stderr_tail
    assert "session id: <REDACTED>" in result.stderr_tail


def test_runtime_preflight_refuses_existing_probe_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")
    probe_path = tmp_path / ".ces-benchmark-runtime-probe.txt"
    probe_path.write_text("user data", encoding="utf-8")

    payload = run_runtime_preflight(runtime="codex", project_root=tmp_path, probe_runtime=True)

    assert payload["recommendation"] == "runtime-blocked"
    assert payload["checks"][1]["ok"] is False
    assert "refusing to overwrite existing" in payload["checks"][1]["detail"]
    assert probe_path.read_text(encoding="utf-8") == "user data"


def test_runtime_preflight_refuses_symlinked_probe_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ces.benchmark.runtime_preflight.shutil.which", lambda name: f"/usr/bin/{name}")
    outside = tmp_path / "outside.txt"
    outside.write_text("safe", encoding="utf-8")
    (tmp_path / ".ces-benchmark-runtime-probe.txt").symlink_to(outside)

    payload = run_runtime_preflight(runtime="codex", project_root=tmp_path, probe_runtime=True)

    assert payload["recommendation"] == "runtime-blocked"
    assert "symlinked" in payload["checks"][1]["detail"]
    assert outside.read_text(encoding="utf-8") == "safe"


def test_probe_commands_use_runtime_safety_flags(tmp_path: Path) -> None:
    codex_command = _probe_command("codex", "/usr/bin/codex", tmp_path)
    claude_command = _probe_command("claude", "/usr/bin/claude", tmp_path)

    assert "--output-last-message" not in codex_command
    assert "workspace-write" in codex_command
    assert "--ask-for-approval" in codex_command
    assert "never" in codex_command
    assert "--ephemeral" in codex_command
    assert "--ignore-user-config" in codex_command
    assert "--ignore-rules" in codex_command
    assert "--no-session-persistence" in claude_command
    assert "--bare" in claude_command
    assert "--strict-mcp-config" in claude_command
    assert "--disable-slash-commands" in claude_command
    assert "Bash,WebFetch,WebSearch" in claude_command


def test_runtime_env_filters_unrelated_secrets_and_preserves_runtime_auth(monkeypatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-pass")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@example.invalid/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-claude")

    codex_env = _runtime_env("codex")
    claude_env = _runtime_env("claude")

    assert codex_env["OPENAI_API_KEY"] == "sk-codex"
    assert "ANTHROPIC_API_KEY" not in codex_env
    assert claude_env["ANTHROPIC_API_KEY"] == "sk-claude"
    assert "OPENAI_API_KEY" not in claude_env
    assert "AWS_SECRET_ACCESS_KEY" not in codex_env
    assert "DATABASE_URL" not in claude_env


def test_runtime_preflight_output_tail_redacts_private_runtime_ids() -> None:
    tail = _safe_tail("session id: 019e62e9-59d9-7c50-8942-d0404764ef89\nAPI_KEY=abc123")

    assert "019e62e9" not in tail
    assert "abc123" not in tail
    assert "session id: <REDACTED>" in tail
    assert "API_KEY=<REDACTED>" in tail


def test_probe_timeout_kills_sigterm_ignoring_process_group(tmp_path: Path) -> None:
    if os.name == "nt":
        return
    child_marker = tmp_path / "child-pgrp.txt"
    script = tmp_path / "spawn_sigterm_ignoring_child.py"
    script.write_text(
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        "child_code = "
        + repr(
            "import os\n"
            "import signal\n"
            "import time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"Path({str(child_marker)!r}).write_text(str(os.getpgrp()), encoding='utf-8')\n"
            "time.sleep(60)\n"
        )
        + "\n"
        "subprocess.Popen([sys.executable, '-c', child_code])\n"
        f"deadline = time.monotonic() + 5\n"
        f"while not os.path.exists({str(child_marker)!r}) and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    result = _run_probe_command([sys.executable, str(script)], cwd=tmp_path, env=os.environ, timeout_seconds=1)

    assert result.exit_code == _TIMEOUT_EXIT_CODE
    process_group_id = int(child_marker.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    while _process_group_has_live_members(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_group_has_live_members(process_group_id)
