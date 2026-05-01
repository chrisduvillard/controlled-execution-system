"""Runtime safety profile disclosure for local agent adapters."""

from __future__ import annotations

from ces.shared.base import CESBaseModel


class RuntimeSafetyProfile(CESBaseModel):
    """Human-readable trust boundary facts for a runtime invocation."""

    runtime_name: str
    tool_allowlist_enforced: bool
    workspace_scoped: bool
    network_policy: str
    effective_allowed_tools: tuple[str, ...]
    notes: str


def safety_profile_for_runtime(runtime_name: str, *, allowed_tools: tuple[str, ...] = ()) -> RuntimeSafetyProfile:
    """Return the effective safety profile for a known runtime."""
    normalized = runtime_name.lower()
    if normalized == "claude":
        tools = allowed_tools or ("Read", "Grep", "Glob", "Edit", "Write")
        return RuntimeSafetyProfile(
            runtime_name="claude",
            tool_allowlist_enforced=True,
            workspace_scoped=True,
            network_policy="runtime default; Bash and WebFetch excluded unless explicitly allowed",
            effective_allowed_tools=tuple(tools),
            notes="Claude receives an explicit --allowedTools list from CES.",
        )
    if normalized == "codex":
        return RuntimeSafetyProfile(
            runtime_name="codex",
            tool_allowlist_enforced=False,
            workspace_scoped=True,
            network_policy="Codex CLI sandbox policy",
            effective_allowed_tools=(),
            notes=(
                "Codex is invoked with --sandbox workspace-write; CES manifest allowed_tools "
                "are not enforced by the Codex adapter."
            ),
        )
    return RuntimeSafetyProfile(
        runtime_name=runtime_name,
        tool_allowlist_enforced=False,
        workspace_scoped=False,
        network_policy="unknown",
        effective_allowed_tools=tuple(allowed_tools),
        notes="CES has no runtime-specific safety profile for this adapter.",
    )
