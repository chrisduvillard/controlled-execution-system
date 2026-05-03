"""Runtime failure diagnostics for builder-first CLI flows."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ces.execution.secrets import scrub_secrets_from_text

_MAX_SECTION_CHARS = 4000
_MAX_SUMMARY_CHARS = 1200

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_part(value: object, fallback: str) -> str:
    rendered = str(value or fallback).strip() or fallback
    return _SAFE_FILENAME_RE.sub("-", rendered).strip("._-") or fallback


def scrub_and_truncate_runtime_output(text: str, *, max_chars: int = _MAX_SECTION_CHARS) -> str:
    """Scrub likely secrets from runtime output and bound artifact size."""
    scrubbed = scrub_secrets_from_text(text or "")
    if len(scrubbed) <= max_chars:
        return scrubbed
    return scrubbed[:max_chars] + f"\n… truncated {len(scrubbed) - max_chars} chars …"


def summarize_runtime_failure(execution: dict[str, Any], *, max_chars: int = _MAX_SUMMARY_CHARS) -> str:
    """Return a concise, redacted runtime failure summary for the operator."""
    runtime = execution.get("runtime_name") or "runtime"
    exit_code = execution.get("exit_code")
    stderr = scrub_and_truncate_runtime_output(str(execution.get("stderr") or ""), max_chars=max_chars)
    stdout = scrub_and_truncate_runtime_output(str(execution.get("stdout") or ""), max_chars=max_chars)
    lines = [f"{runtime} exited with code {exit_code}."]
    if stderr:
        lines.extend(["", "Runtime stderr:", stderr])
    elif stdout:
        lines.extend(["", "Runtime stdout:", stdout])
    else:
        lines.extend(["", "Runtime produced no stdout or stderr."])
    invocation_ref = execution.get("invocation_ref")
    if invocation_ref:
        lines.extend(["", f"Invocation: {invocation_ref}"])
    transcript_path = execution.get("transcript_path")
    if transcript_path:
        lines.append(f"Transcript: {transcript_path}")
    return "\n".join(lines)


def write_runtime_diagnostics(project_root: Path, manifest_id: str, execution: dict[str, Any]) -> Path:
    """Write a redacted runtime failure artifact and return its absolute path."""
    diagnostics_dir = project_root / ".ces" / "runtime-diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(diagnostics_dir, 0o700)
    except OSError:
        pass
    filename = f"{_safe_part(manifest_id, 'manifest')}-{_safe_part(execution.get('invocation_ref'), 'runtime')}.txt"
    path = diagnostics_dir / filename
    content = "\n".join(
        [
            "# CES Runtime Failure Diagnostics",
            "",
            f"Runtime: {execution.get('runtime_name') or 'unknown'}",
            f"Runtime version: {execution.get('runtime_version') or 'unknown'}",
            f"Exit code: {execution.get('exit_code')}",
            f"Invocation: {execution.get('invocation_ref') or 'unknown'}",
            f"Transcript: {execution.get('transcript_path') or '(none)'}",
            "",
            "## stderr",
            scrub_and_truncate_runtime_output(str(execution.get("stderr") or "")) or "(empty)",
            "",
            "## stdout",
            scrub_and_truncate_runtime_output(str(execution.get("stdout") or "")) or "(empty)",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
