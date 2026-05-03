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
    mcp_servers_requested: tuple[str, ...] = ()
    mcp_grounding_supported: bool = False
    mcp_grounding_notes: str = ""
    accepted_runtime_side_effect_risk: bool = False
    runtime_auth_env_keys: tuple[str, ...] = ()
    notes: str


def safety_profile_for_runtime(
    runtime_name: str,
    *,
    allowed_tools: tuple[str, ...] = (),
    mcp_servers: tuple[str, ...] = (),
) -> RuntimeSafetyProfile:
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
            mcp_servers_requested=tuple(mcp_servers),
            mcp_grounding_supported=True,
            mcp_grounding_notes=_mcp_notes(mcp_servers, supported=True),
            runtime_auth_env_keys=("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE"),
            notes="Claude receives an explicit --allowedTools list from CES.",
        )
    if normalized == "codex":
        # Codex runs with full host access in Chris's CES deployment because
        # Codex's bubblewrap-backed workspace-write sandbox cannot execute shell
        # tools on this host. This is intentionally disclosed as not workspace
        # scoped so unattended builds still require explicit side-effect consent.
        return RuntimeSafetyProfile(
            runtime_name="codex",
            tool_allowlist_enforced=False,
            workspace_scoped=False,
            network_policy="Codex CLI danger-full-access policy",
            effective_allowed_tools=(),
            mcp_servers_requested=tuple(mcp_servers),
            mcp_grounding_supported=False,
            mcp_grounding_notes=_mcp_notes(mcp_servers, supported=False),
            runtime_auth_env_keys=(
                "CODEX_HOME",
                "CODEX_SANDBOX",
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_API_BASE",
                "OPENAI_ORG_ID",
                "OPENAI_ORGANIZATION",
                "OPENAI_PROJECT",
            ),
            notes=(
                "Codex is invoked with --sandbox danger-full-access; CES manifest allowed_tools "
                "are not enforced by the Codex adapter."
            ),
        )
    return RuntimeSafetyProfile(
        runtime_name=runtime_name,
        tool_allowlist_enforced=False,
        workspace_scoped=False,
        network_policy="unknown",
        effective_allowed_tools=tuple(allowed_tools),
        mcp_servers_requested=tuple(mcp_servers),
        mcp_grounding_supported=False,
        mcp_grounding_notes=_mcp_notes(mcp_servers, supported=False),
        notes="CES has no runtime-specific safety profile for this adapter.",
    )


def runtime_side_effects_block_auto_approval(profile: RuntimeSafetyProfile, *, accepted: bool) -> bool:
    """Return True when unattended approval must stop for runtime side-effect risk."""
    if accepted:
        return False
    return not profile.tool_allowlist_enforced


def _mcp_notes(mcp_servers: tuple[str, ...], *, supported: bool) -> str:
    if not mcp_servers:
        return "No manifest MCP servers requested."
    names = ", ".join(mcp_servers)
    if supported:
        return f"Manifest MCP grounding requested for: {names}."
    return f"Manifest MCP grounding requested for {names}, but this adapter does not configure MCP servers."
