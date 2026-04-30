"""Tests for parse_completion_claim — extracts a CompletionClaim from agent stdout.

The agent emits its claim inside a fenced block tagged ``ces:completion``. The
parser tolerates surrounding text and is permissive about JSON whitespace, but
returns None on any failure (parsing, schema). The verifier surfaces "no claim"
as a SCHEMA_VIOLATION; this parser stays narrow.
"""

from __future__ import annotations

from ces.execution.completion_parser import parse_completion_claim

_VALID_BLOCK = """\
Some preamble from the agent...

```ces:completion
{
  "task_id": "MANIF-001",
  "summary": "Implemented login endpoint",
  "files_changed": ["src/auth/login.py"],
  "criteria_satisfied": [],
  "open_questions": [],
  "scope_deviations": []
}
```

And some chatter after.
"""


def test_parse_finds_claim_from_fenced_block() -> None:
    claim = parse_completion_claim(_VALID_BLOCK)
    assert claim is not None
    assert claim.task_id == "MANIF-001"
    assert claim.files_changed == ("src/auth/login.py",)


def test_parse_returns_none_when_no_block() -> None:
    assert parse_completion_claim("Just some text, no block.") is None


def test_parse_returns_none_on_invalid_json() -> None:
    text = """```ces:completion
{ not valid json
```"""
    assert parse_completion_claim(text) is None


def test_parse_returns_none_when_required_field_missing() -> None:
    text = """```ces:completion
{"summary": "no task_id"}
```"""
    assert parse_completion_claim(text) is None


def test_parse_finds_claim_with_criteria_and_deviations() -> None:
    text = """```ces:completion
{
  "task_id": "T-1",
  "summary": "did it",
  "files_changed": ["a.py"],
  "criteria_satisfied": [
    {"criterion": "tests pass", "evidence": "412 passed", "evidence_kind": "command_output"}
  ],
  "open_questions": ["should we cache?"],
  "scope_deviations": ["refactored b.py"]
}
```"""
    claim = parse_completion_claim(text)
    assert claim is not None
    assert len(claim.criteria_satisfied) == 1
    assert claim.criteria_satisfied[0].criterion == "tests pass"
    assert claim.scope_deviations == ("refactored b.py",)


def test_parse_handles_first_block_when_multiple_present() -> None:
    """Defensive: pick the first block; later blocks are ignored."""
    text = """```ces:completion
{"task_id": "T-FIRST", "summary": "s", "files_changed": []}
```

```ces:completion
{"task_id": "T-SECOND", "summary": "s", "files_changed": []}
```"""
    claim = parse_completion_claim(text)
    assert claim is not None
    assert claim.task_id == "T-FIRST"


def test_parse_empty_string_returns_none() -> None:
    assert parse_completion_claim("") is None
