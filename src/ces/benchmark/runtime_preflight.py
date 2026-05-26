"""Runtime readiness probes for measured A/B benchmark runs."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, Mapping, NamedTuple

from ces.execution._subprocess_env import build_subprocess_env
from ces.shared.secrets import scrub_secrets_from_text

RuntimeName = Literal["codex", "claude"]

_PROBE_FILENAME = ".ces-benchmark-runtime-probe.txt"
_PROBE_TEXT = "ces-benchmark-runtime-ready"
_STREAM_LIMIT = 500
_TIMEOUT_EXIT_CODE = 124
_TERMINATE_GRACE_SECONDS = 0.5
_KILL_GRACE_SECONDS = 2.0
_SESSION_ID_RE = re.compile(r"(?im)^(session id:\s*)[0-9a-f-]{16,}.*$")
_CODEX_ENV_KEYS = (
    "CODEX_HOME",
    "CODEX_SANDBOX",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
)
_CLAUDE_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "CLAUDECODE",
    "CLAUDE_CODE",
)


class _ProbeResult(NamedTuple):
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    timed_out: bool = False


def run_runtime_preflight(
    *,
    runtime: RuntimeName,
    project_root: Path,
    probe_runtime: bool = False,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Return benchmark runtime readiness without claiming product evidence.

    The optional write probe intentionally asks the selected runtime to create a
    single probe file inside ``project_root``. It is a benchmark-readiness check,
    not a CES-vs-vanilla benchmark run.
    """

    resolved_root = project_root.resolve()
    executable = shutil.which(runtime)
    checks: list[dict[str, Any]] = []
    installed = executable is not None
    checks.append(
        {
            "name": "runtime-installed",
            "ok": installed,
            "detail": f"{runtime} found on PATH" if installed else f"{runtime} not found on PATH",
        }
    )

    if not installed:
        checks.append(
            {
                "name": "workspace-write-probe",
                "ok": False if probe_runtime else None,
                "detail": "skipped because runtime is missing",
            }
        )
        return _payload(runtime, resolved_root, probe_runtime, installed, "runtime-missing", checks)

    if not probe_runtime:
        checks.append(
            {
                "name": "workspace-write-probe",
                "ok": None,
                "detail": "not run; pass --probe-runtime to verify workspace writes",
            }
        )
        return _payload(runtime, resolved_root, probe_runtime, installed, "runtime-not-verified", checks)

    resolved_root.mkdir(parents=True, exist_ok=True)
    probe_path = resolved_root / _PROBE_FILENAME
    precheck_error = _probe_path_precheck(probe_path)
    if precheck_error:
        checks.append(
            {
                "name": "workspace-write-probe",
                "ok": False,
                "detail": precheck_error,
                "exit_code": None,
                "stdout_tail": "",
                "stderr_tail": "",
            }
        )
        return _payload(runtime, resolved_root, probe_runtime, installed, "runtime-blocked", checks)

    command = _probe_command(runtime, executable, resolved_root)
    result = _run_probe_command(
        command,
        cwd=resolved_root,
        env=_runtime_env(runtime),
        timeout_seconds=timeout_seconds,
    )
    probe_ok, probe_detail = _probe_file_status(probe_path)
    exit_ok = result.exit_code == 0
    if probe_ok:
        _safe_unlink_probe(probe_path)
    checks.append(
        {
            "name": "workspace-write-probe",
            "ok": probe_ok and exit_ok,
            "detail": (
                f"runtime created {_PROBE_FILENAME} inside project root"
                if probe_ok and exit_ok
                else probe_detail or "runtime exited without creating benchmark probe file"
            ),
            "exit_code": result.exit_code,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
        }
    )
    if result.timed_out:
        checks[-1]["detail"] = f"runtime probe timed out after {timeout_seconds}s"
    return _payload(
        runtime,
        resolved_root,
        probe_runtime,
        installed,
        "runtime-ready" if probe_ok and exit_ok else "runtime-blocked",
        checks,
    )


def _payload(
    runtime: RuntimeName,
    project_root: Path,
    probe_runtime: bool,
    installed: bool,
    recommendation: str,
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "runtime": runtime,
        "project_root": str(project_root),
        "probe_runtime": probe_runtime,
        "installed": installed,
        "recommendation": recommendation,
        "checks": checks,
    }


def _probe_path_precheck(probe_path: Path) -> str | None:
    try:
        if probe_path.is_symlink():
            return f"refusing to write probe through symlinked {probe_path.name}"
        if probe_path.exists():
            return f"refusing to overwrite existing {probe_path.name}"
    except OSError as exc:
        return f"could not inspect probe path before runtime launch: {type(exc).__name__}"
    return None


def _probe_file_status(probe_path: Path) -> tuple[bool, str]:
    try:
        if probe_path.is_symlink():
            return False, f"runtime produced symlinked {probe_path.name}; refusing to read it"
        if not probe_path.is_file():
            return False, "runtime exited without creating benchmark probe file"
        content = probe_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"could not read runtime probe file: {type(exc).__name__}"
    if content == _PROBE_TEXT:
        return True, ""
    return False, f"runtime wrote unexpected probe content to {probe_path.name}"


def _safe_unlink_probe(probe_path: Path) -> None:
    try:
        if probe_path.is_file() and not probe_path.is_symlink():
            probe_path.unlink()
    except OSError:
        pass


def _runtime_env(runtime: RuntimeName) -> dict[str, str]:
    extra_keys = _CODEX_ENV_KEYS if runtime == "codex" else _CLAUDE_ENV_KEYS
    env = build_subprocess_env(extra_keys)
    if runtime == "claude":
        env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return env


def _probe_command(runtime: RuntimeName, executable: str, project_root: Path) -> list[str]:
    prompt = (
        f"Create a file named {_PROBE_FILENAME} in the current working directory. "
        f"The file must contain exactly {_PROBE_TEXT}. Do not edit any other files."
    )
    if runtime == "codex":
        return [
            executable,
            "--cd",
            str(project_root),
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            prompt,
        ]
    return [
        executable,
        "-p",
        prompt,
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Write",
        "--disallowedTools",
        "Bash,WebFetch,WebSearch",
        "--add-dir",
        str(project_root),
        "--no-session-persistence",
        "--bare",
        "--strict-mcp-config",
        "--disable-slash-commands",
    ]


def _run_probe_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> _ProbeResult:
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_file,
            "stderr": stderr_file,
            "cwd": cwd,
            "env": dict(env),
        }
        if _supports_process_groups():
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **popen_kwargs)  # noqa: S603 - executable is validated by runtime name.
        except OSError as exc:
            return _ProbeResult(
                exit_code=None,
                stdout_tail="",
                stderr_tail=_safe_tail(f"runtime probe failed before launch: {type(exc).__name__}"),
            )
        process_group_id = _process_group_id(process)
        try:
            process.communicate(timeout=timeout_seconds)
            exit_code = int(process.returncode or 0)
            timed_out = False
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process, process_group_id)
            exit_code = _TIMEOUT_EXIT_CODE
            timed_out = True
        return _ProbeResult(
            exit_code=exit_code,
            stdout_tail=_safe_tail(_read_limited_file(stdout_file)),
            stderr_tail=_safe_tail(_read_limited_file(stderr_file)),
            timed_out=timed_out,
        )


def _supports_process_groups() -> bool:
    return os.name != "nt" and hasattr(os, "killpg") and hasattr(os, "getpgid")


def _process_group_id(process: subprocess.Popen[Any]) -> int | None:
    if not _supports_process_groups():
        return None
    try:
        return os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        return None


def _terminate_process_tree(process: subprocess.Popen[Any], process_group_id: int | None) -> None:
    if _supports_process_groups() and process_group_id is not None:
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        if _wait_for_process_group_exit(process, process_group_id, timeout_seconds=_TERMINATE_GRACE_SECONDS):
            return
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        if _wait_for_process_group_exit(process, process_group_id, timeout_seconds=_KILL_GRACE_SECONDS):
            return
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _process_group_has_live_members(process_group_id: int) -> bool:
    proc_root = Path("/proc")
    if proc_root.is_dir():
        try:
            proc_entries = list(proc_root.iterdir())
        except OSError:
            proc_entries = []
        for entry in proc_entries:
            if not entry.name.isdigit():
                continue
            try:
                stat_text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            stat_parts = stat_text.rsplit(")", maxsplit=1)
            if len(stat_parts) != 2:
                continue
            fields = stat_parts[1].strip().split()
            # After the command name, /proc/<pid>/stat fields are:
            # state, ppid, pgrp, session, ...
            if len(fields) < 3:
                continue
            state = fields[0]
            try:
                pgrp = int(fields[2])
            except ValueError:
                continue
            if pgrp == process_group_id and state != "Z":
                return True
        return False
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return False
    return True


def _wait_for_process_group_exit(
    process: subprocess.Popen[Any],
    process_group_id: int,
    *,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is None:
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        if not _process_group_has_live_members(process_group_id):
            return True
        time.sleep(0.05)
    return not _process_group_has_live_members(process_group_id)


def _read_limited_file(handle: Any) -> bytes:
    if not hasattr(handle, "seek") or not hasattr(handle, "read"):
        return b""
    handle.seek(0)
    data = handle.read(_STREAM_LIMIT + 1)
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    return data[:_STREAM_LIMIT]


def _safe_tail(text: str | bytes) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    sanitized = scrub_secrets_from_text(text)
    sanitized = _SESSION_ID_RE.sub(r"\1<REDACTED>", sanitized)
    sanitized = sanitized.replace(str(Path.home()), "~")
    sanitized = sanitized.strip()
    if len(sanitized) <= _STREAM_LIMIT:
        return sanitized
    return sanitized[-_STREAM_LIMIT:]
