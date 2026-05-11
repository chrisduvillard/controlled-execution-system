"""Deterministic transcript pattern extraction for harness evolution."""

from __future__ import annotations

import re

from ces.execution.secrets import scrub_secrets_from_text

_RUN_ID_RE = re.compile(r"\b(?:run[_ -]?id|task[_ -]?id|manifest[_ -]?id)\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE)
_COMMAND_PREFIX_RE = re.compile(r"^\s*(?:command|cmd|\$|>)\s*[: ]\s*(.+?)\s*$", re.IGNORECASE)
_VALIDATION_TOKEN_RE = re.compile(
    r"\b(?:uv\s+run\s+)?(?:pytest|ruff|mypy|pip-audit|twine|coverage|python\s+-m\s+pytest|npm\s+test|go\s+test|cargo\s+test)\b",
    re.IGNORECASE,
)
_FAIL_RE = re.compile(r"\b(?:FAILED|FAILURES|failed|error|traceback|AssertionError|exit code\s*[1-9])\b")
_PASS_RE = re.compile(r"\b(?:passed|success|all checks passed|exit code\s*0)\b", re.IGNORECASE)
_PROXY_RE = re.compile(
    r"\b(?:assume|assumed|not run|without running|looks good|manual|proxy|inspect(?:ed)? only)\b", re.IGNORECASE
)


def extract_task_run_id(lines: list[str]) -> str | None:
    """Extract a stable run id from transcript metadata when present."""

    for line in lines:
        match = _RUN_ID_RE.search(line)
        if match:
            return scrub_secrets_from_text(match.group(1))
    return None


def extract_validation_commands(lines: list[str]) -> list[str]:
    """Return unique validation commands observed in the transcript."""

    commands: list[str] = []
    seen: set[str] = set()
    for line in lines:
        candidate = _command_candidate(line)
        if candidate is None or not _VALIDATION_TOKEN_RE.search(candidate):
            continue
        command = scrub_secrets_from_text(candidate)
        if command not in seen:
            commands.append(command)
            seen.add(command)
    return commands


def classify_outcome(lines: list[str]) -> str:
    """Classify coarse outcome from deterministic transcript markers."""

    joined = "\n".join(lines)
    if _FAIL_RE.search(joined):
        return "fail"
    if _PASS_RE.search(joined):
        return "pass"
    return "unknown"


def classify_failure(outcome: str, commands: list[str]) -> str:
    """Classify failure class without depending on raw transcript snippets."""

    if outcome == "pass":
        return "none"
    if outcome == "fail" and commands:
        return "validation_failure"
    if outcome == "fail":
        return "execution_failure"
    return "unknown"


def suspected_root_cause(outcome: str, failure_class: str) -> str:
    """Return a conservative suspected root cause label."""

    if outcome == "pass":
        return "no failure detected"
    if failure_class == "validation_failure":
        return "validation command failed"
    if failure_class == "execution_failure":
        return "transcript contains failure markers without validation command evidence"
    return "insufficient evidence"


def proxy_validation_warnings(lines: list[str]) -> list[str]:
    """Detect lines suggesting validation by proxy rather than executed checks."""

    warnings: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if _PROXY_RE.search(line):
            warnings.append(f"line {idx}: proxy validation phrase detected")
    return warnings


def evidence_pointers(
    *, lines: list[str], source_path: str | None, commands: list[str], warnings: list[str]
) -> list[str]:
    """Build line/source pointers without copying raw transcript evidence."""

    pointers: list[str] = []
    if source_path:
        pointers.append(f"source: {source_path}")
    if commands:
        pointers.append("validation commands observed")
    if warnings:
        pointers.append("proxy-validation warning lines observed")
    if classify_outcome(lines) == "fail":
        pointers.append("failure markers observed")
    return pointers


def _command_candidate(line: str) -> str | None:
    match = _COMMAND_PREFIX_RE.match(line)
    if match:
        return match.group(1).strip()
    stripped = line.strip()
    return stripped if _VALIDATION_TOKEN_RE.search(stripped) else None
