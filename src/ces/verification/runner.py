"""Run independent local verification commands."""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.execution.processes import run_sync_command
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
    expected_exit_codes: tuple[int, ...]
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
        result = run_sync_command(
            shlex.split(command.command),
            cwd=cwd,
            timeout_seconds=command.timeout_seconds,
        )
        exit_code = result.exit_code
        stdout = result.stdout
        stderr = result.stderr
        expected_exit_codes = tuple(command.expected_exit_codes or (0,))
        results.append(
            VerificationCommandResult(
                id=command.id,
                kind=command.kind,
                command=command.command,
                required=command.required,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                expected_exit_codes=expected_exit_codes,
                passed=exit_code in expected_exit_codes,
            )
        )
    passed = bool(results) and all(result.passed or not result.required for result in results)
    return VerificationRunResult(passed=passed, commands=tuple(results))
