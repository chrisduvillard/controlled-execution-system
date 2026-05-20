"""Objective-bound proof fingerprints for CES completion evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from ces.shared.secrets import scrub_secrets_recursive
from ces.verification.completion_contract import CompletionContract

_SCHEMA_VERSION = "1.0"
_BINDING_RUNTIME_KEYS = (
    "project_mode",
    "constraints",
    "must_not_break",
    "source_of_truth",
    "critical_flows",
    "brownfield_entry_ids",
    "brownfield_dispositions",
)


@dataclass(frozen=True)
class ProofBinding:
    """Deterministic objective/context fingerprint for proof evidence."""

    schema_version: str
    project_mode: str
    objective: str
    project_type: str
    acceptance_criteria: tuple[dict[str, str], ...]
    runtime_context: dict[str, Any]
    behavior_delta: dict[str, list[str]]
    verification_commands: tuple[dict[str, Any], ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), sort_keys=True))


def build_proof_binding(contract: CompletionContract) -> ProofBinding:
    """Build a proof binding from a completion contract."""

    return build_proof_binding_from_payload(contract.to_dict())


def build_proof_binding_from_payload(payload: dict[str, Any]) -> ProofBinding:
    """Build a proof binding from a JSON-native completion contract payload."""

    material = _binding_material(payload)
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return ProofBinding(content_hash=digest, **material)


def proof_binding_hash(contract: CompletionContract) -> str:
    """Return the current objective/context binding hash for a contract."""

    return build_proof_binding(contract).content_hash


def proof_binding_hash_from_payload(payload: dict[str, Any]) -> str:
    """Return the binding hash for a JSON-native completion contract payload."""

    return build_proof_binding_from_payload(payload).content_hash


def _binding_material(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _dict(payload.get("runtime"))
    runtime_context = {key: runtime[key] for key in _BINDING_RUNTIME_KEYS if key in runtime}
    project_mode = str(runtime_context.get("project_mode") or runtime.get("mode") or "unknown")
    material = {
        "schema_version": _SCHEMA_VERSION,
        "project_mode": project_mode,
        "objective": str(payload.get("request", "")),
        "project_type": str(payload.get("project_type", "unknown")),
        "acceptance_criteria": tuple(_acceptance(item) for item in _list(payload.get("acceptance_criteria"))),
        "runtime_context": _stable(scrub_secrets_recursive(runtime_context)),
        "behavior_delta": _behavior_delta(_dict(payload.get("behavior_delta"))),
        "verification_commands": tuple(_command(item) for item in _list(payload.get("inferred_commands"))),
    }
    return _stable(scrub_secrets_recursive(material))


def _acceptance(item: Any) -> dict[str, str]:
    source = _dict(item)
    return {"id": str(source.get("id", "")), "text": str(source.get("text", ""))}


def _command(item: Any) -> dict[str, Any]:
    source = _dict(item)
    return {
        "id": str(source.get("id", "")),
        "kind": str(source.get("kind", "")),
        "command": str(source.get("command", "")),
        "required": bool(source.get("required", True)),
        "cwd": str(source.get("cwd", ".")),
        "timeout_seconds": int(source.get("timeout_seconds", 120)),
        "expected_exit_codes": tuple(int(code) for code in _list(source.get("expected_exit_codes", [0]))),
    }


def _behavior_delta(source: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "added": _strings(source.get("added")),
        "modified": _strings(source.get("modified")),
        "removed": _strings(source.get("removed")),
        "preserved": _strings(source.get("preserved")),
        "unknown": _strings(source.get("unknown")),
    }


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in _list(value) if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return tuple(_stable(item) for item in value)
    return value
