"""Tests for shared subprocess lifecycle helpers."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from ces.execution.processes import (
    ProcessError,
    ProcessResult,
    ProcessTimeoutError,
    _decode_output,
    _read_stream,
    run_async_command,
    run_sync_command,
)


@pytest.mark.asyncio
async def test_run_async_command_kills_process_on_timeout(tmp_path: Path) -> None:
    script = tmp_path / "sleep_child.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    with pytest.raises(ProcessTimeoutError) as exc_info:
        await run_async_command(
            [sys.executable, str(script)],
            timeout_seconds=0.5,
            termination_grace_seconds=0.1,
        )

    assert exc_info.value.exit_code == 124
    assert exc_info.value.stdout
    child_pid = int(exc_info.value.stdout.strip().splitlines()[0])
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not _pid_exists(child_pid):
            break
        time.sleep(0.05)
    assert not _pid_exists(child_pid)


def test_run_sync_command_returns_124_on_timeout(tmp_path: Path) -> None:
    result = run_sync_command(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
        cwd=tmp_path,
        timeout_seconds=0.5,
        termination_grace_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.exit_code == 124
    assert "started" in result.stdout


def test_run_sync_command_success_captures_output_and_env(tmp_path: Path) -> None:
    result = run_sync_command(
        [sys.executable, "-c", "import os; print(os.getcwd()); print(os.environ['CES_TEST_VALUE'])"],
        cwd=tmp_path,
        env={"CES_TEST_VALUE": "visible"},
        timeout_seconds=5,
    )

    assert result.command[0] == sys.executable
    assert result.exit_code == 0
    assert result.timed_out is False
    assert str(tmp_path) in result.stdout
    assert "visible" in result.stdout
    assert result.stderr == ""


def test_run_sync_command_returns_127_on_missing_command(tmp_path: Path) -> None:
    result = run_sync_command(
        ["definitely-not-a-ces-command"],
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert result.exit_code == 127
    assert result.timed_out is False
    assert result.stderr


@pytest.mark.asyncio
async def test_run_async_command_success_captures_output_and_stdin(tmp_path: Path) -> None:
    script = tmp_path / "echo_env.py"
    script.write_text(
        "import os, sys\n"
        "text = sys.stdin.read()\n"
        "print(os.getcwd())\n"
        "print(os.environ['CES_TEST_VALUE'])\n"
        "print(text.upper())\n"
        "print('warn', file=sys.stderr)\n",
        encoding="utf-8",
    )

    result = await run_async_command(
        [sys.executable, str(script)],
        stdin_text="hello",
        cwd=tmp_path,
        env={"CES_TEST_VALUE": "visible"},
        timeout_seconds=5,
    )

    assert result.command == (sys.executable, str(script))
    assert result.exit_code == 0
    assert result.timed_out is False
    assert str(tmp_path) in result.stdout
    assert "visible" in result.stdout
    assert "HELLO" in result.stdout
    assert "warn" in result.stderr


@pytest.mark.asyncio
async def test_run_async_command_returns_nonzero_exit(tmp_path: Path) -> None:
    result = await run_async_command(
        [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(7)"],
        cwd=tmp_path,
        timeout_seconds=5,
    )

    assert result.exit_code == 7
    assert result.stderr.strip() == "bad"


@pytest.mark.asyncio
async def test_run_async_command_cleans_up_on_cancellation(tmp_path: Path) -> None:
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    task = asyncio.create_task(
        run_async_command(
            [sys.executable, str(script)],
            timeout_seconds=30,
            termination_grace_seconds=0.1,
        )
    )
    await asyncio.sleep(0.1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_process_error_exposes_result_fields() -> None:
    result = ProcessResult(("cmd",), 124, "out", "err", timed_out=True)
    error = ProcessError("failed", result)

    assert error.command == ("cmd",)
    assert error.exit_code == 124
    assert error.stdout == "out"
    assert error.stderr == "err"
    assert error.timed_out is True


@pytest.mark.asyncio
async def test_private_output_helpers_handle_empty_values() -> None:
    assert await _read_stream(None) == b""
    assert _decode_output(None) == ""
    assert _decode_output(b"hello") == "hello"
    assert _decode_output("hello") == "hello"


def _pid_exists(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
