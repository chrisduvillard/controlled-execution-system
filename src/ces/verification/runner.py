"""Run independent local verification commands."""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ces.execution.processes import run_sync_command
from ces.execution.secrets import scrub_secrets_from_text
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
    cwd: str
    timeout_seconds: int
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
    resolved_project_root = project_root.resolve()
    results: list[VerificationCommandResult] = []
    for command in commands:
        cwd = _resolve_command_cwd(resolved_project_root, command.cwd)
        result = run_sync_command(
            shlex.split(command.command),
            cwd=cwd,
            timeout_seconds=command.timeout_seconds,
        )
        exit_code = result.exit_code
        stdout = scrub_secrets_from_text(result.stdout)
        stderr = scrub_secrets_from_text(result.stderr)
        expected_exit_codes = tuple(command.expected_exit_codes or (0,))
        results.append(
            VerificationCommandResult(
                id=command.id,
                kind=command.kind,
                command=scrub_secrets_from_text(command.command),
                required=command.required,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                cwd=command.cwd,
                timeout_seconds=command.timeout_seconds,
                expected_exit_codes=expected_exit_codes,
                passed=exit_code in expected_exit_codes,
            )
        )
    passed = bool(results) and all(result.passed or not result.required for result in results)
    return VerificationRunResult(passed=passed, commands=tuple(results))


def _resolve_command_cwd(project_root: Path, cwd: str) -> Path:
    """Resolve a verification cwd without allowing project-root escapes."""

    cwd_path = Path(cwd)
    if cwd_path.is_absolute():
        raise ValueError("verification command cwd must be relative to the project root")
    try:
        resolved_root = project_root.resolve()
        resolved_cwd = (resolved_root / cwd_path).resolve()
        resolved_cwd.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError("verification command cwd must stay inside the project root") from exc
    return resolved_cwd
