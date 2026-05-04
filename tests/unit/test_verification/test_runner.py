"""Tests for local verification command runner."""

from __future__ import annotations

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
