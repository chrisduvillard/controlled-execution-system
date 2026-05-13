"""Runtime safety profile disclosure for local agent adapters."""

from __future__ import annotations

import os

from ces.shared.base import CESBaseModel

_DEFAULT_CODEX_SANDBOX = "danger-full-access"
_INVALID_CODEX_SANDBOX_FALLBACK = "read-only"
_WORKSPACE_SCOPED_CODEX_SANDBOXES = {"read-only", "workspace-write"}
_ALLOWED_CODEX_SANDBOXES = {*_WORKSPACE_SCOPED_CODEX_SANDBOXES, _DEFAULT_CODEX_SANDBOX}


def codex_sandbox_mode() -> str:
    """Return the CES-selected Codex sandbox mode.

    ``danger-full-access`` remains the default for Chris's local deployment
    when no override is present. Operators can opt into Codex's own workspace
    sandbox with ``CES_CODEX_SANDBOX=workspace-write`` or ``read-only`` when
    their host can support it.

    If an explicit override is invalid, fail closed to ``read-only`` rather
    than silently expanding back to full-host access or passing arbitrary CLI
    flags through.
    """
    raw_requested = os.environ.get("CES_CODEX_SANDBOX")
    if raw_requested is None:
        return _DEFAULT_CODEX_SANDBOX
    requested = raw_requested.strip()
    return requested if requested in _ALLOWED_CODEX_SANDBOXES else _INVALID_CODEX_SANDBOX_FALLBACK


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
        sandbox = codex_sandbox_mode()
        workspace_scoped = sandbox in _WORKSPACE_SCOPED_CODEX_SANDBOXES
        # Codex defaults to full host access in Chris's CES deployment because
        # Codex's bubblewrap-backed workspace-write sandbox historically could
        # not execute shell tools on this host. Operators can opt into Codex's
        # own workspace sandbox via CES_CODEX_SANDBOX when their host supports
        # it. CES still cannot enforce manifest allowed_tools inside Codex.
        return RuntimeSafetyProfile(
            runtime_name="codex",
            tool_allowlist_enforced=False,
            workspace_scoped=workspace_scoped,
            network_policy=f"Codex CLI --sandbox {sandbox} policy",
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
                f"Codex sandbox risk is intentionally disclosed: invoked with --sandbox {sandbox}; CES manifest "
                "allowed_tools are not enforced by the Codex adapter. Use CES_CODEX_SANDBOX to opt into read-only "
                "or workspace-write when the local host supports Codex sandboxing."
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


def runtime_side_effects_require_pre_execution_consent(profile: RuntimeSafetyProfile, *, accepted: bool) -> bool:
    """Return True when a runtime must be explicitly accepted before launch.

    Approval-time gates are too late for runtimes that can already mutate the
    workspace or host before CES reviews the result. Fail closed before
    subprocess launch when the selected adapter cannot enforce the manifest's
    tool boundary or cannot keep execution workspace-scoped.
    """
    if accepted:
        return False
    return not profile.tool_allowlist_enforced or not profile.workspace_scoped


def _mcp_notes(mcp_servers: tuple[str, ...], *, supported: bool) -> str:
    if not mcp_servers:
        return "No manifest MCP servers requested."
    names = ", ".join(mcp_servers)
    if supported:
        return f"Manifest MCP grounding requested for: {names}."
    return f"Manifest MCP grounding requested for {names}, but this adapter does not configure MCP servers."
