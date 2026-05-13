"""Tests for runtime failure diagnostics helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

from ces.cli._runtime_diagnostics import (
    scrub_and_truncate_runtime_output,
    summarize_runtime_failure,
    write_runtime_diagnostics,
)


def test_scrub_and_truncate_runtime_output_redacts_before_truncating() -> None:
    secret = "sk-" + "runtime-diagnostics-secret"

    rendered = scrub_and_truncate_runtime_output(f"prefix {secret} suffix", max_chars=18)

    assert secret not in rendered
    assert "<REDACTED>" in rendered
    assert "truncated" in rendered


def test_summarize_runtime_failure_prefers_redacted_stderr() -> None:
    secret = "sk-" + "stderr-secret"

    summary = summarize_runtime_failure(
        {
            "runtime_name": "codex",
            "exit_code": 1,
            "stdout": "stdout should be hidden when stderr exists",
            "stderr": f"OPENAI_API_KEY={secret}",
            "invocation_ref": "inv-123",
            "transcript_path": "runtime-transcripts/transcript.txt",
        }
    )

    assert "codex exited with code 1" in summary
    assert "Runtime stderr:" in summary
    assert "Runtime stdout:" not in summary
    assert secret not in summary
    assert "OPENAI_API_KEY=<REDACTED>" in summary
    assert "Invocation: inv-123" in summary
    assert "Transcript: runtime-transcripts/transcript.txt" in summary


def test_summarize_runtime_failure_uses_stdout_when_stderr_empty() -> None:
    summary = summarize_runtime_failure({"runtime_name": "claude", "exit_code": 2, "stdout": "partial log"})

    assert "claude exited with code 2" in summary
    assert "Runtime stdout:" in summary
    assert "partial log" in summary


def test_summarize_runtime_failure_handles_silent_runtime() -> None:
    summary = summarize_runtime_failure({"exit_code": 124})

    assert "runtime exited with code 124" in summary
    assert "Runtime produced no stdout or stderr." in summary


def test_write_runtime_diagnostics_sanitizes_filename_content_and_permissions(tmp_path: Path) -> None:
    secret = "sk-" + "diagnostic-secret"

    path = write_runtime_diagnostics(
        tmp_path,
        "M unsafe/id",
        {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "exit_code": 1,
            "invocation_ref": "inv unsafe/id",
            "transcript_path": None,
            "stderr": f"TOKEN={secret}",
            "stdout": "ok",
        },
    )

    assert path.name == "M-unsafe-id-inv-unsafe-id.txt"
    assert path.parent == tmp_path / ".ces" / "runtime-diagnostics"
    content = path.read_text(encoding="utf-8")
    assert secret not in content
    assert "TOKEN=<REDACTED>" in content
    if os.name != "nt":
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_runtime_diagnostics_continues_when_chmod_fails(tmp_path: Path) -> None:
    with patch("ces.cli._runtime_diagnostics.os.chmod", side_effect=OSError("chmod denied")):
        path = write_runtime_diagnostics(
            tmp_path,
            "M-1",
            {"runtime_name": "codex", "exit_code": 1, "stdout": "ok"},
        )

    assert path.exists()
    assert "ok" in path.read_text(encoding="utf-8")
