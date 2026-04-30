"""Extracts a CompletionClaim from agent stdout (P1d).

Convention: the agent emits its claim inside a fenced block tagged
``ces:completion``. Any text outside the block is ignored. Parsing failures
return ``None`` rather than raise — the CompletionVerifier escalates a missing
or unparseable claim as a SCHEMA_VIOLATION finding so the agent gets one
unified failure surface.

Example agent output::

    Working on the task...

    ```ces:completion
    {"task_id": "MANIF-001", "summary": "...", "files_changed": [...], ...}
    ```

    Done.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from ces.harness.models.completion_claim import CompletionClaim

_BLOCK_RE = re.compile(
    r"```ces:completion\s*\n(?P<json>.*?)\n```",
    re.DOTALL,
)


def parse_completion_claim(stdout: str) -> CompletionClaim | None:
    """Extract the first ``ces:completion`` block from stdout, if present.

    Returns the parsed :class:`CompletionClaim` on success. Returns ``None``
    when no block exists, the JSON is invalid, or the JSON does not satisfy
    the CompletionClaim schema. The caller (CompletionVerifier) treats
    ``None`` as a SCHEMA_VIOLATION finding.

    Uses ``model_validate_json`` so that JSON-native lists become tuples on
    the immutable model — matching the project's tuples-not-lists convention.
    """
    if not stdout:
        return None

    match = _BLOCK_RE.search(stdout)
    if match is None:
        return None

    try:
        return CompletionClaim.model_validate_json(match.group("json"))
    except ValidationError:
        return None
