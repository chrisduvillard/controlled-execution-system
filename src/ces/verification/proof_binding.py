"""Objective-bound proof fingerprints for CES completion evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from ces.shared.secrets import scrub_secrets_recursive
from ces.verification.completion_contract import CompletionContract

_SCHEMA_VERSION = "1.1"
_LEGACY_SCHEMA_VERSION = "1.0"
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
    reality_boundary: dict[str, Any]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        payload = json.loads(json.dumps(asdict(self), sort_keys=True))
        if self.schema_version == _LEGACY_SCHEMA_VERSION:
            payload.pop("reality_boundary", None)
        return payload


def build_proof_binding(contract: CompletionContract) -> ProofBinding:
    """Build a proof binding from a completion contract."""

    from ces.verification.completion_contract import _contract_storage_dict

    return build_proof_binding_from_payload(_contract_storage_dict(contract))


def build_proof_binding_from_payload(payload: dict[str, Any]) -> ProofBinding:
    """Build a proof binding from a JSON-native completion contract payload."""

    material = _binding_material(payload)
    digest_material = _digest_material(material, payload)
    digest = hashlib.sha256(
        json.dumps(digest_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
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
        "schema_version": _SCHEMA_VERSION if _has_reality_boundary(payload) else _LEGACY_SCHEMA_VERSION,
        "project_mode": project_mode,
        "objective": str(payload.get("request", "")),
        "project_type": str(payload.get("project_type", "unknown")),
        "acceptance_criteria": tuple(_acceptance(item) for item in _list(payload.get("acceptance_criteria"))),
        "runtime_context": _stable(scrub_secrets_recursive(runtime_context)),
        "behavior_delta": _behavior_delta(_dict(payload.get("behavior_delta"))),
        "verification_commands": tuple(_command(item) for item in _list(payload.get("inferred_commands"))),
        "reality_boundary": _reality_boundary(_dict(payload.get("reality_boundary"))),
    }
    return _stable(scrub_secrets_recursive(material))


def _digest_material(material: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Return hash material, preserving v1.0 hashes for contracts without reality_boundary."""

    if _has_reality_boundary(payload):
        return material
    legacy = dict(material)
    legacy.pop("reality_boundary", None)
    return legacy


def _has_reality_boundary(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("reality_boundary"), dict)


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


def _reality_boundary(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": int(source.get("contract_version", 1)),
        "success_predicates": tuple(_predicate(item) for item in _list(source.get("success_predicates"))),
        "official_evaluators": tuple(_evaluator(item) for item in _list(source.get("official_evaluators"))),
        "protected_surfaces": tuple(_protected_surface(item) for item in _list(source.get("protected_surfaces"))),
        "mutable_test_policy": str(source.get("mutable_test_policy", "warn") or "warn"),
        "allowed_test_paths_state": _list_state(source, "allowed_test_paths"),
        "allowed_test_paths_count": _list_count(source, "allowed_test_paths"),
        "allowed_test_paths_sha256": tuple(_hash_strings(source, "allowed_test_paths")),
        "denied_test_paths_state": _list_state(source, "denied_test_paths"),
        "denied_test_paths_count": _list_count(source, "denied_test_paths"),
        "denied_test_paths_sha256": tuple(_hash_strings(source, "denied_test_paths")),
        "predicate_hash": _optional_str(source.get("predicate_hash")),
        "contract_frozen_at": _optional_str(source.get("contract_frozen_at")),
    }


def _optional_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _predicate(item: Any) -> dict[str, str]:
    source = _dict(item)
    return {
        "id": str(source.get("id", "")),
        "source": str(source.get("source", "acceptance_criterion") or "acceptance_criterion"),
        "text_state": _raw_state(source, "text"),
        "text_sha256": _payload_hash(source, raw_key="text", hash_key="text_sha256"),
    }


def _evaluator(item: Any) -> dict[str, Any]:
    source = _dict(item)
    return {
        "id": str(source.get("id", "")),
        "command_id": str(source.get("command_id", source.get("id", ""))),
        "kind": str(source.get("kind", "")),
        "required": bool(source.get("required", True)),
        "command_state": _raw_state(source, "command"),
        "command_sha256": _payload_hash(source, raw_key="command", hash_key="command_sha256"),
        "cwd_state": _raw_state(source, "cwd"),
        "cwd_sha256": _payload_hash(source, raw_key="cwd", hash_key="cwd_sha256", default="."),
        "timeout_seconds": int(source.get("timeout_seconds", 120)),
        "expected_exit_codes": tuple(int(code) for code in _list(source.get("expected_exit_codes", [0]))),
    }


def _protected_surface(item: Any) -> dict[str, str]:
    source = _dict(item)
    return {
        "path_state": _raw_state(source, "path"),
        "path_sha256": _payload_hash(source, raw_key="path", hash_key="path_sha256"),
        "reason_state": _raw_state(source, "reason"),
        "reason_sha256": _payload_hash(source, raw_key="reason", hash_key="reason_sha256"),
    }


def _hash_strings(source: dict[str, Any], key: str) -> list[str]:
    hash_key = f"{key}_sha256"
    raw_items = _strings(source.get(key))
    stored_hashes = _strings(source.get(hash_key))
    if not raw_items:
        return stored_hashes
    return [
        stored_hashes[index]
        if index < len(stored_hashes) and (not item or "<REDACTED>" in item)
        else _sha256_text(item)
        for index, item in enumerate(raw_items)
    ]


def _raw_state(source: dict[str, Any], key: str) -> str:
    if key not in source:
        computed = "missing"
    else:
        raw = str(source.get(key, ""))
        if not raw:
            computed = "empty"
        elif "<REDACTED>" in raw:
            computed = "redacted"
        else:
            computed = "raw"
    stored = source.get(f"{key}_state")
    if isinstance(stored, str) and stored in {"missing", "empty", "redacted"}:
        return stored
    return computed


def _list_state(source: dict[str, Any], key: str) -> str:
    if key not in source:
        computed = "missing"
    else:
        items = _strings(source.get(key))
        if not items:
            computed = "empty"
        elif all("<REDACTED>" in item for item in items):
            computed = "redacted"
        else:
            computed = "raw"
    stored = source.get(f"{key}_state")
    if isinstance(stored, str) and stored in {"missing", "empty", "redacted"}:
        return stored
    return computed


def _list_count(source: dict[str, Any], key: str) -> int:
    if key not in source:
        return -1
    return len(_strings(source.get(key)))


def _payload_hash(source: dict[str, Any], *, raw_key: str, hash_key: str, default: str = "") -> str:
    if raw_key in source:
        raw = str(source.get(raw_key, default))
        if raw and "<REDACTED>" not in raw:
            return _sha256_text(raw)
    stored = source.get(hash_key)
    if isinstance(stored, str) and stored:
        return stored
    return _sha256_text(str(source.get(raw_key, default)))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


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
