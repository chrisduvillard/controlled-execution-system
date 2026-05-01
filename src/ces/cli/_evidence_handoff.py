"""Typed helpers for expert commands that consume persisted evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PersistedEvidenceView:
    manifest_id: str
    packet_id: str | None
    triage_color: str
    summary: str
    challenge: str | None
    reason: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, fallback_manifest_id: str) -> PersistedEvidenceView | None:
        triage_color = payload.get("triage_color")
        if not triage_color:
            return None
        summary = str(payload.get("summary") or "Persisted evidence packet")
        return cls(
            manifest_id=str(payload.get("manifest_id") or fallback_manifest_id),
            packet_id=str(payload["packet_id"]) if payload.get("packet_id") else None,
            triage_color=str(triage_color),
            summary=summary,
            challenge=str(payload["challenge"]) if payload.get("challenge") else None,
            reason=str(payload.get("triage_reason") or summary),
        )


def load_persisted_evidence_view(
    *,
    local_store: Any,
    manifest_id: str,
    evidence_packet_id: str | None,
) -> PersistedEvidenceView | None:
    if local_store is None:
        return None
    payload = None
    if evidence_packet_id:
        get_by_packet = getattr(local_store, "get_evidence_by_packet_id", None)
        if callable(get_by_packet):
            payload = get_by_packet(evidence_packet_id)
    if payload is None:
        get_evidence = getattr(local_store, "get_evidence", None)
        if callable(get_evidence):
            payload = get_evidence(manifest_id)
    if not isinstance(payload, dict):
        return None
    return PersistedEvidenceView.from_payload(payload, fallback_manifest_id=manifest_id)
