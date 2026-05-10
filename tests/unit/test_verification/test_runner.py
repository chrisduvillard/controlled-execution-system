"""Tests for local verification command runner."""

from __future__ import annotations

import sys
from pathlib import Path


def test_runner_captures_pass_and_fail(tmp_path: Path) -> None:
    from ces.verification.completion_contract import VerificationCommand
    from ces.verification.runner import run_verification_commands

    results = run_verification_commands(
        tmp_path,
        (
            VerificationCommand(id="VC-001", kind="smoke", command="python -c 'print(123)'"),
            VerificationCommand(id="VC-002", kind="smoke", command="python -c 'import sys; sys.exit(2)'"),
        ),
    )

    assert results.passed is False
    assert results.commands[0].passed is True
    assert "123" in results.commands[0].stdout
    assert results.commands[1].exit_code == 2


def test_runner_fails_when_no_commands_are_inferred(tmp_path: Path) -> None:
    from ces.verification.runner import run_verification_commands

    result = run_verification_commands(tmp_path, ())

    assert result.passed is False
    assert result.commands == ()


def test_runner_accepts_expected_nonzero_exit_code(tmp_path: Path) -> None:
    from ces.verification.completion_contract import VerificationCommand
    from ces.verification.runner import run_verification_commands

    result = run_verification_commands(
        tmp_path,
        (
            VerificationCommand(
                id="VC-negative",
                kind="negative-smoke",
                command="python -c 'import sys; sys.exit(1)'",
                expected_exit_codes=(1,),
            ),
        ),
    )

    assert result.passed is True
    assert result.commands[0].exit_code == 1
    assert result.commands[0].expected_exit_codes == (1,)
    assert result.commands[0].passed is True


def test_runner_returns_124_on_timeout(tmp_path: Path) -> None:
    from ces.verification.completion_contract import VerificationCommand
    from ces.verification.runner import run_verification_commands

    result = run_verification_commands(
        tmp_path,
        (
            VerificationCommand(
                id="VC-timeout",
                kind="smoke",
                command=f"{sys.executable} -c 'import time; print(123, flush=True); time.sleep(30)'",
                timeout_seconds=0.5,
            ),
        ),
    )

    assert result.passed is False
    assert result.commands[0].exit_code == 124
    assert result.commands[0].passed is False
    assert "123" in result.commands[0].stdout


def test_runner_returns_127_on_missing_command(tmp_path: Path) -> None:
    from ces.verification.completion_contract import VerificationCommand
    from ces.verification.runner import run_verification_commands

    result = run_verification_commands(
        tmp_path,
        (
            VerificationCommand(
                id="VC-missing",
                kind="smoke",
                command="definitely-not-a-ces-command",
            ),
        ),
    )

    assert result.passed is False
    assert result.commands[0].exit_code == 127
    assert result.commands[0].passed is False
    assert result.commands[0].stderr
