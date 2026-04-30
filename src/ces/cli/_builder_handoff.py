"""Helpers for resolving expert-command targets from the current builder session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import typer


@dataclass(frozen=True)
class BuilderHandoffContext:
    manifest_id: str | None
    evidence_packet_id: str | None
    request: str | None
    project_mode: str | None


def load_builder_handoff_context(local_store: Any) -> BuilderHandoffContext | None:
    get_snapshot = getattr(local_store, "get_latest_builder_session_snapshot", None)
    if not callable(get_snapshot):
        return None
    snapshot = get_snapshot()
    if not isinstance(getattr(snapshot, "request", None), str):
        return None
    manifest = getattr(snapshot, "manifest", None)
    evidence = getattr(snapshot, "evidence", None)
    return BuilderHandoffContext(
        manifest_id=getattr(manifest, "manifest_id", None),
        evidence_packet_id=evidence.get("packet_id") if isinstance(evidence, dict) else None,
        request=getattr(snapshot, "request", None),
        project_mode=getattr(snapshot, "project_mode", None),
    )


def resolve_manifest_id(
    *,
    provided_ref: str | None,
    local_store: Any,
    missing_message: str,
) -> tuple[str, BuilderHandoffContext | None]:
    context = load_builder_handoff_context(local_store)
    if provided_ref:
        if context is not None and provided_ref == context.evidence_packet_id and context.manifest_id:
            return context.manifest_id, context
        get_evidence_by_packet_id = getattr(local_store, "get_evidence_by_packet_id", None)
        if callable(get_evidence_by_packet_id):
            evidence = get_evidence_by_packet_id(provided_ref)
            if isinstance(evidence, dict) and evidence.get("manifest_id"):
                return str(evidence["manifest_id"]), context
        return provided_ref, context
    if context is not None and context.manifest_id:
        return context.manifest_id, context
    raise typer.BadParameter(missing_message)
