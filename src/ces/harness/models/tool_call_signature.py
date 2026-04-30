"""Tool-call signature model for no-progress loop detection (P4).

A tool call signature is a stable identifier for a (tool_name, args) pair.
Signatures are compared across retries to detect "no-progress" loops where an
agent re-issues the same call without state changing in between — the
20-iteration / $12-spend failure mode documented across n8n / LangChain
issue threads.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ces.shared.base import CESBaseModel


class ToolCallSignature(CESBaseModel):
    """Stable identifier for a tool invocation.

    Two ToolCallSignature instances are equal when they have the same
    ``tool_name`` and ``args_hash``. ``args_hash`` is a SHA-256 hex digest
    of the JSON-serialised, key-sorted arguments — which makes the hash
    insensitive to dict ordering but sensitive to value differences.
    """

    tool_name: str
    args_hash: str

    @classmethod
    def from_call(cls, tool_name: str, args: Any) -> ToolCallSignature:
        """Build a signature from a tool name + arbitrary args structure."""
        return cls(tool_name=tool_name, args_hash=hash_tool_args(args))


def hash_tool_args(args: Any) -> str:
    """Produce a stable SHA-256 hex digest of tool arguments.

    Accepts any JSON-serialisable structure; falls back to ``repr()`` for
    objects that aren't natively serialisable.
    """
    try:
        serialised = json.dumps(args, sort_keys=True, default=repr)
    except (TypeError, ValueError):
        serialised = repr(args)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
