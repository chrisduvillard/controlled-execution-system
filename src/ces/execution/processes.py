"""Shared subprocess lifecycle helpers for CES-launched commands."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessResult:
    """Completed subprocess result."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ProcessError(RuntimeError):
    """Base error for managed subprocess failures."""

    def __init__(self, message: str, result: ProcessResult) -> None:
        super().__init__(message)
        self.result = result

    @property
    def command(self) -> tuple[str, ...]:
        return self.result.command

    @property
    def exit_code(self) -> int:
        return self.result.exit_code

    @property
    def stdout(self) -> str:
        return self.result.stdout

    @property
    def stderr(self) -> str:
        return self.result.stderr

    @property
    def timed_out(self) -> bool:
        return self.result.timed_out


class ProcessTimeoutError(ProcessError):
    """Raised when a managed subprocess times out after cleanup."""


async def run_async_command(
    command: Sequence[str],
    *,
    stdin_text: str | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | int,
    termination_grace_seconds: float = 5.0,
) -> ProcessResult:
    """Run an async command and clean up its process tree on timeout/cancellation."""
    command_tuple = tuple(str(part) for part in command)
    proc = await asyncio.create_subprocess_exec(
        *command_tuple,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        **_process_group_kwargs(),
    )
    stdout_task = asyncio.create_task(_read_stream(proc.stdout))
    stderr_task = asyncio.create_task(_read_stream(proc.stderr))
    try:
        if stdin_text is not None and proc.stdin is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(stdin_text.encode())
                await proc.stdin.drain()
            proc.stdin.close()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await proc.stdin.wait_closed()
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        stdout_bytes, stderr_bytes = await asyncio.gather(stdout_task, stderr_task)
    except TimeoutError as exc:
        await _cleanup_async_process(proc, termination_grace_seconds=termination_grace_seconds)
        stdout_bytes, stderr_bytes = await _collect_reader_tasks(
            stdout_task,
            stderr_task,
            timeout_seconds=termination_grace_seconds,
        )
        result = ProcessResult(
            command=command_tuple,
            exit_code=124,
            stdout=_decode_output(stdout_bytes),
            stderr=_decode_output(stderr_bytes),
            timed_out=True,
        )
        raise ProcessTimeoutError(
            f"Command timed out after {timeout_seconds}s: {command_tuple[0]}",
            result,
        ) from exc
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await asyncio.shield(_cleanup_async_process(proc, termination_grace_seconds=termination_grace_seconds))
        for task in (stdout_task, stderr_task):
            task.cancel()
        raise

    return ProcessResult(
        command=command_tuple,
        exit_code=int(proc.returncode or 0),
        stdout=_decode_output(stdout_bytes),
        stderr=_decode_output(stderr_bytes),
        timed_out=False,
    )


def run_sync_command(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | int,
    termination_grace_seconds: float = 5.0,
) -> ProcessResult:
    """Run a synchronous command and clean up its process tree on timeout."""
    command_tuple = tuple(str(part) for part in command)
    try:
        proc = subprocess.Popen(  # noqa: S603 - caller supplies already-tokenized local command
            command_tuple,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_process_group_kwargs(),
        )
    except OSError as exc:
        return ProcessResult(
            command=command_tuple,
            exit_code=127,
            stdout="",
            stderr=str(exc),
            timed_out=False,
        )

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        stdout, stderr = _cleanup_sync_process(
            proc,
            termination_grace_seconds=termination_grace_seconds,
        )
        return ProcessResult(
            command=command_tuple,
            exit_code=124,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr),
            timed_out=True,
        )

    return ProcessResult(
        command=command_tuple,
        exit_code=int(proc.returncode or 0),
        stdout=stdout or "",
        stderr=stderr or "",
        timed_out=False,
    )


async def _cleanup_async_process(
    proc: asyncio.subprocess.Process,
    *,
    termination_grace_seconds: float,
) -> None:
    _terminate_process_tree(proc.pid, proc)
    try:
        await asyncio.wait_for(proc.wait(), timeout=termination_grace_seconds)
    except TimeoutError:
        _kill_process_tree(proc.pid, proc)
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), timeout=termination_grace_seconds)


async def _read_stream(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        return b""
    return await stream.read()


async def _collect_reader_tasks(
    stdout_task: asyncio.Task[bytes],
    stderr_task: asyncio.Task[bytes],
    *,
    timeout_seconds: float,
) -> tuple[bytes, bytes]:
    tasks = (stdout_task, stderr_task)
    done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    stdout = _finished_task_result(stdout_task, done)
    stderr = _finished_task_result(stderr_task, done)
    return stdout, stderr


def _finished_task_result(task: asyncio.Task[bytes], done: set[asyncio.Task[bytes]]) -> bytes:
    if task not in done or task.cancelled() or task.exception() is not None:
        return b""
    return task.result()


def _cleanup_sync_process(
    proc: subprocess.Popen[str],
    *,
    termination_grace_seconds: float,
) -> tuple[str, str]:
    _terminate_process_tree(proc.pid, proc)
    try:
        return proc.communicate(timeout=termination_grace_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid, proc)
        try:
            return proc.communicate(timeout=termination_grace_seconds)
        except subprocess.TimeoutExpired:
            return "", ""


def _process_group_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_process_tree(pid: int, proc: Any) -> None:
    if sys.platform != "win32":
        try:
            os.killpg(pid, signal.SIGTERM)
            return
        except ProcessLookupError:
            return
    with contextlib.suppress(ProcessLookupError, RuntimeError):  # pragma: no cover - Windows fallback
        proc.terminate()


def _kill_process_tree(pid: int, proc: Any) -> None:
    if sys.platform != "win32":
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
    with contextlib.suppress(ProcessLookupError, RuntimeError):  # pragma: no cover - Windows fallback
        proc.kill()


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
