"""Run independent local verification commands."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.verification.completion_contract import VerificationCommand


@dataclass(frozen=True)
class VerificationCommandResult:
    id: str
    kind: str
    command: str
    required: bool
    exit_code: int
    stdout: str
    stderr: str
    passed: bool


@dataclass(frozen=True)
class VerificationRunResult:
    passed: bool
    commands: tuple[VerificationCommandResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_verification_commands(
    project_root: Path,
    commands: tuple[VerificationCommand, ...],
) -> VerificationRunResult:
    results: list[VerificationCommandResult] = []
    for command in commands:
        cwd = project_root / command.cwd if command.cwd != "." else project_root
        try:
            completed = subprocess.run(  # noqa: S603 - contract commands are local verification steps
                shlex.split(command.command),
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=command.timeout_seconds,
                check=False,
            )
            exit_code = int(completed.returncode)
            stdout = completed.stdout
            stderr = completed.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            exit_code = 124 if isinstance(exc, subprocess.TimeoutExpired) else 127
            stdout = getattr(exc, "stdout", "") or ""
            stderr = str(exc)
        results.append(
            VerificationCommandResult(
                id=command.id,
                kind=command.kind,
                command=command.command,
                required=command.required,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                passed=exit_code == 0,
            )
        )
    passed = bool(results) and all(result.passed or not result.required for result in results)
    return VerificationRunResult(passed=passed, commands=tuple(results))
