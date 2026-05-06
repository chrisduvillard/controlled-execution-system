"""Evidence packet integrity helpers for merge-time validation."""

from __future__ import annotations

from typing import Any

from ces.shared.crypto import sha256_hash

_REVIEWED_EVIDENCE_HASH_KEYS = {"reviewed_evidence_hash", "evidence_content_hash"}
_MANIFEST_HASH_KEYS = ("manifest_hash", "manifest_content_hash")


def canonical_reviewed_evidence_payload(evidence_packet: dict[str, Any]) -> dict[str, Any]:
    """Return the payload covered by the reviewed-evidence hash.

    Integrity fields are excluded so callers can embed the hash in the packet
    without creating a recursive digest. All other top-level fields are part of
    the operator-reviewed payload.
    """
    return {key: value for key, value in evidence_packet.items() if key not in _REVIEWED_EVIDENCE_HASH_KEYS}


def compute_reviewed_evidence_hash(evidence_packet: dict[str, Any]) -> str:
    """Compute the canonical hash for an operator-reviewed evidence packet."""
    return sha256_hash(canonical_reviewed_evidence_payload(evidence_packet))


def extract_reviewed_evidence_hash(evidence_packet: dict[str, Any]) -> str | None:
    """Return the embedded reviewed-evidence hash, accepting legacy alias."""
    for key in _REVIEWED_EVIDENCE_HASH_KEYS:
        value = evidence_packet.get(key)
        if value:
            return str(value)
    return None


def extract_evidence_manifest_hash(evidence_packet: dict[str, Any]) -> str | None:
    """Return the manifest hash embedded inside an evidence packet."""
    for key in _MANIFEST_HASH_KEYS:
        value = evidence_packet.get(key)
        if value:
            return str(value)
    return None
