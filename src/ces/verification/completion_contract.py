"""Structured completion contract for greenfield CES builds."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from ces.local_state_path import read_text_project_path, write_text_project_path
from ces.shared.enums import RiskTier
from ces.shared.secrets import scrub_secrets_recursive


@dataclass(frozen=True)
class AcceptanceCriterion:
    id: str
    text: str


@dataclass(frozen=True)
class VerificationCommand:
    id: str
    kind: str
    command: str
    required: bool = True
    cwd: str = "."
    timeout_seconds: int = 120
    expected_exit_codes: tuple[int, ...] = (0,)


@dataclass(frozen=True)
class SuccessPredicate:
    """Frozen external success predicate that runtime self-report cannot redefine."""

    id: str
    text: str
    source: str = "acceptance_criterion"
    text_sha256: str | None = None
    text_state: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SuccessPredicate:
        return cls(
            id=str(payload.get("id", "")),
            text=str(payload.get("text", "")),
            source=str(payload.get("source", "acceptance_criterion") or "acceptance_criterion"),
            text_sha256=str(payload["text_sha256"]) if isinstance(payload.get("text_sha256"), str) else None,
            text_state=_field_state(payload, "text"),
        )


@dataclass(frozen=True)
class OfficialEvaluator:
    """Verifier definition treated as evidence source of truth, not agent narrative."""

    id: str
    command_id: str
    kind: str
    command: str
    required: bool = True
    cwd: str = "."
    timeout_seconds: int = 120
    expected_exit_codes: tuple[int, ...] = (0,)
    command_sha256: str | None = None
    cwd_sha256: str | None = None
    command_state: str | None = None
    cwd_state: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OfficialEvaluator:
        return cls(
            id=str(payload.get("id", "")),
            command_id=str(payload.get("command_id", payload.get("id", ""))),
            kind=str(payload.get("kind", "")),
            command=str(payload.get("command", "")),
            required=bool(payload.get("required", True)),
            cwd=str(payload.get("cwd", ".")),
            timeout_seconds=int(payload.get("timeout_seconds", 120)),
            expected_exit_codes=_expected_exit_codes(payload),
            command_sha256=str(payload["command_sha256"]) if isinstance(payload.get("command_sha256"), str) else None,
            cwd_sha256=str(payload["cwd_sha256"]) if isinstance(payload.get("cwd_sha256"), str) else None,
            command_state=_field_state(payload, "command"),
            cwd_state=_field_state(payload, "cwd"),
        )


@dataclass(frozen=True)
class ProtectedSurface:
    """Path surface that should not be weakened without explicit operator approval."""

    path: str
    reason: str
    path_sha256: str | None = None
    reason_sha256: str | None = None
    path_state: str | None = None
    reason_state: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProtectedSurface:
        return cls(
            path=str(payload.get("path", "")),
            reason=str(payload.get("reason", "")),
            path_sha256=str(payload["path_sha256"]) if isinstance(payload.get("path_sha256"), str) else None,
            reason_sha256=str(payload["reason_sha256"]) if isinstance(payload.get("reason_sha256"), str) else None,
            path_state=_field_state(payload, "path"),
            reason_state=_field_state(payload, "reason"),
        )


@dataclass(frozen=True)
class RealityBoundaryContract:
    """Measurement contract for Reality Boundary / Reality Loop Lite evidence."""

    success_predicates: tuple[SuccessPredicate, ...] = ()
    official_evaluators: tuple[OfficialEvaluator, ...] = ()
    protected_surfaces: tuple[ProtectedSurface, ...] = ()
    mutable_test_policy: str = "warn"
    allowed_test_paths: tuple[str, ...] = ()
    denied_test_paths: tuple[str, ...] = ()
    allowed_test_paths_sha256: tuple[str, ...] = ()
    denied_test_paths_sha256: tuple[str, ...] = ()
    allowed_test_paths_state: str | None = None
    denied_test_paths_state: str | None = None
    predicate_hash: str | None = None
    contract_frozen_at: str | None = None
    contract_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> RealityBoundaryContract:
        if not payload:
            return cls()
        source = payload
        return cls(
            success_predicates=tuple(
                SuccessPredicate.from_dict(item) for item in _dict_list(source.get("success_predicates"))
            ),
            official_evaluators=tuple(
                OfficialEvaluator.from_dict(item) for item in _dict_list(source.get("official_evaluators"))
            ),
            protected_surfaces=tuple(
                ProtectedSurface.from_dict(item) for item in _dict_list(source.get("protected_surfaces"))
            ),
            mutable_test_policy=str(source.get("mutable_test_policy", "warn") or "warn"),
            allowed_test_paths=_string_tuple(source.get("allowed_test_paths")),
            denied_test_paths=_string_tuple(source.get("denied_test_paths")),
            allowed_test_paths_sha256=_string_tuple(source.get("allowed_test_paths_sha256")),
            denied_test_paths_sha256=_string_tuple(source.get("denied_test_paths_sha256")),
            allowed_test_paths_state=_list_field_state(source, "allowed_test_paths"),
            denied_test_paths_state=_list_field_state(source, "denied_test_paths"),
            predicate_hash=str(source["predicate_hash"]) if isinstance(source.get("predicate_hash"), str) else None,
            contract_frozen_at=str(source["contract_frozen_at"])
            if isinstance(source.get("contract_frozen_at"), str)
            else None,
            contract_version=int(source.get("contract_version", 1)),
        )

    def with_predicate_hash(self) -> RealityBoundaryContract:
        material = scrub_secrets_recursive(self.to_dict())
        material.pop("predicate_hash", None)
        digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return replace(self, predicate_hash=digest)


def verification_commands_for_contract(contract: CompletionContract) -> tuple[VerificationCommand, ...]:
    """Return the authoritative commands that prove a completion contract."""

    if not contract.reality_boundary.official_evaluators:
        return contract.inferred_commands
    return tuple(
        VerificationCommand(
            id=evaluator.command_id or evaluator.id,
            kind=evaluator.kind,
            command=evaluator.command,
            required=evaluator.required,
            cwd=evaluator.cwd,
            timeout_seconds=evaluator.timeout_seconds,
            expected_exit_codes=evaluator.expected_exit_codes,
        )
        for evaluator in contract.reality_boundary.official_evaluators
    )


@dataclass(frozen=True)
class BehaviorDelta:
    """Brownfield behavior categories carried into completion proof."""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    def has_signal(self) -> bool:
        """Return whether any behavior-delta category contains information."""

        return any((self.added, self.modified, self.removed, self.preserved, self.unknown))

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> BehaviorDelta:
        source = payload or {}
        return cls(
            added=_string_tuple(source.get("added")),
            modified=_string_tuple(source.get("modified")),
            removed=_string_tuple(source.get("removed")),
            preserved=_string_tuple(source.get("preserved")),
            unknown=_string_tuple(source.get("unknown")),
        )


@dataclass(frozen=True)
class RiskTrack:
    """Risk-adaptive evidence requirements attached to a completion contract."""

    tier: str = RiskTier.C.value
    required_artifacts: tuple[str, ...] = ()
    proof_requirements: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> RiskTrack:
        source = payload or {}
        tier = _risk_tier_value(source.get("tier"))
        return cls(
            tier=tier,
            required_artifacts=_string_tuple(source.get("required_artifacts")),
            proof_requirements=_string_tuple(source.get("proof_requirements")),
            evidence_requirements=_string_tuple(source.get("evidence_requirements")),
        )


def infer_risk_track(delta: BehaviorDelta) -> RiskTrack:
    """Infer a conservative risk track from brownfield behavior deltas."""

    if delta.unknown or delta.removed:
        return RiskTrack(
            tier=RiskTier.A.value,
            required_artifacts=("rollback-plan.md", "reviewer-signoff.md"),
            proof_requirements=(
                "Document high-risk behavior evidence.",
                "Document rollback path before approval.",
            ),
            evidence_requirements=(
                "Fresh verification passed.",
                "Rollback path documented.",
                "Reviewer signoff recorded.",
            ),
        )
    if delta.modified or delta.preserved:
        return RiskTrack(
            tier=RiskTier.B.value,
            required_artifacts=("regression-evidence.md",),
            proof_requirements=("Document regression evidence for modified or preserved behavior.",),
            evidence_requirements=("Fresh verification passed.", "Regression evidence recorded."),
        )
    return RiskTrack(
        tier=RiskTier.C.value,
        evidence_requirements=("Fresh verification passed.",),
    )


@dataclass(frozen=True)
class CompletionContract:
    request: str
    project_type: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    inferred_commands: tuple[VerificationCommand, ...] = ()
    runtime: dict[str, Any] = field(default_factory=dict)
    required_artifacts: tuple[str, ...] = ()
    proof_requirements: tuple[str, ...] = ()
    behavior_delta: BehaviorDelta = field(default_factory=BehaviorDelta)
    risk_track: RiskTrack = field(default_factory=RiskTrack)
    reality_boundary: RealityBoundaryContract = field(default_factory=RealityBoundaryContract)
    proof_binding_hash: str | None = None
    next_ces_command: str = "ces verify --json"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native dictionary for durable CLI evidence."""

        payload = json.loads(json.dumps(asdict(self)))
        if self.reality_boundary == RealityBoundaryContract():
            payload.pop("reality_boundary", None)
        elif isinstance(payload.get("reality_boundary"), dict):
            payload["reality_boundary"] = _safe_reality_boundary_dict(self.reality_boundary)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompletionContract:
        behavior_delta = BehaviorDelta.from_dict(_dict_or_none(payload.get("behavior_delta")))
        risk_track_payload = _dict_or_none(payload.get("risk_track"))
        return cls(
            version=int(payload.get("version", 1)),
            request=str(payload.get("request", "")),
            project_type=str(payload.get("project_type", "unknown")),
            acceptance_criteria=tuple(
                AcceptanceCriterion(id=str(item["id"]), text=str(item["text"]))
                for item in payload.get("acceptance_criteria", [])
            ),
            inferred_commands=tuple(
                VerificationCommand(
                    id=str(item["id"]),
                    kind=str(item["kind"]),
                    command=str(item["command"]),
                    required=bool(item.get("required", True)),
                    cwd=str(item.get("cwd", ".")),
                    timeout_seconds=int(item.get("timeout_seconds", 120)),
                    expected_exit_codes=_expected_exit_codes(item),
                )
                for item in payload.get("inferred_commands", [])
            ),
            runtime=dict(payload.get("runtime", {}) or {}),
            required_artifacts=tuple(str(item) for item in payload.get("required_artifacts", []) or []),
            proof_requirements=tuple(str(item) for item in payload.get("proof_requirements", []) or []),
            behavior_delta=behavior_delta,
            risk_track=RiskTrack.from_dict(risk_track_payload)
            if risk_track_payload is not None
            else infer_risk_track(behavior_delta),
            reality_boundary=RealityBoundaryContract.from_dict(_dict_or_none(payload.get("reality_boundary"))),
            proof_binding_hash=str(payload["proof_binding_hash"])
            if isinstance(payload.get("proof_binding_hash"), str)
            else None,
            next_ces_command=str(payload.get("next_ces_command", "ces verify --json") or "ces verify --json"),
        )

    def write(self, path: Path) -> None:
        _write_contract_text(path, json.dumps(_contract_storage_dict(self), indent=2) + "\n")

    @classmethod
    def read(cls, path: Path) -> CompletionContract:
        project_root = _project_root_for_ces_path(path)
        if project_root is not None:
            payload = read_text_project_path(project_root, path)
        else:
            payload = path.read_text(encoding="utf-8")
        return cls.from_dict(json.loads(payload))


def criteria_from_texts(texts: list[str] | tuple[str, ...]) -> tuple[AcceptanceCriterion, ...]:
    return tuple(
        AcceptanceCriterion(id=f"AC-{index:03d}", text=text.strip())
        for index, text in enumerate(texts, start=1)
        if text.strip()
    )


def _contract_storage_dict(contract: CompletionContract) -> dict[str, Any]:
    """Return full contract storage material, preserving verifier fields needed for reads."""

    payload = json.loads(json.dumps(asdict(contract)))
    if contract.reality_boundary == RealityBoundaryContract():
        payload.pop("reality_boundary", None)
    elif isinstance(payload.get("reality_boundary"), dict):
        payload["reality_boundary"] = scrub_secrets_recursive(_reality_boundary_storage_dict(contract.reality_boundary))
    return payload


def _reality_boundary_storage_dict(boundary: RealityBoundaryContract) -> dict[str, Any]:
    """Return storage boundary with raw fields plus stable hashes for scrubbed reloads."""

    payload = json.loads(json.dumps(asdict(boundary)))
    for index, predicate in enumerate(boundary.success_predicates):
        payload["success_predicates"][index]["text_sha256"] = predicate.text_sha256 or _sha256_text(predicate.text)
        payload["success_predicates"][index]["text_state"] = predicate.text_state or _field_state(
            {"text": predicate.text}, "text"
        )
    for index, evaluator in enumerate(boundary.official_evaluators):
        payload["official_evaluators"][index]["command_sha256"] = evaluator.command_sha256 or _sha256_text(
            evaluator.command
        )
        payload["official_evaluators"][index]["cwd_sha256"] = evaluator.cwd_sha256 or _sha256_text(evaluator.cwd)
        payload["official_evaluators"][index]["command_state"] = evaluator.command_state or _field_state(
            {"command": evaluator.command}, "command"
        )
        payload["official_evaluators"][index]["cwd_state"] = evaluator.cwd_state or _field_state(
            {"cwd": evaluator.cwd}, "cwd"
        )
    for index, surface in enumerate(boundary.protected_surfaces):
        payload["protected_surfaces"][index]["path_sha256"] = surface.path_sha256 or _sha256_text(surface.path)
        payload["protected_surfaces"][index]["reason_sha256"] = surface.reason_sha256 or _sha256_text(surface.reason)
        payload["protected_surfaces"][index]["path_state"] = surface.path_state or _field_state(
            {"path": surface.path}, "path"
        )
        payload["protected_surfaces"][index]["reason_state"] = surface.reason_state or _field_state(
            {"reason": surface.reason}, "reason"
        )
    payload["allowed_test_paths_sha256"] = list(
        _trusted_or_raw_hashes(boundary.allowed_test_paths, boundary.allowed_test_paths_sha256)
    )
    payload["denied_test_paths_sha256"] = list(
        _trusted_or_raw_hashes(boundary.denied_test_paths, boundary.denied_test_paths_sha256)
    )
    payload["allowed_test_paths_state"] = boundary.allowed_test_paths_state or _list_field_state(
        {"allowed_test_paths": boundary.allowed_test_paths}, "allowed_test_paths"
    )
    payload["denied_test_paths_state"] = boundary.denied_test_paths_state or _list_field_state(
        {"denied_test_paths": boundary.denied_test_paths}, "denied_test_paths"
    )
    return payload


def _safe_reality_boundary_dict(boundary: RealityBoundaryContract) -> dict[str, Any]:
    """Return evidence-safe boundary metadata without raw predicates, commands, or local paths."""

    return {
        "contract_version": boundary.contract_version,
        "success_predicates": [
            {
                "id": predicate.id,
                "source": predicate.source,
                "text_sha256": _trusted_or_raw_hash(predicate.text, predicate.text_sha256),
            }
            for predicate in boundary.success_predicates
        ],
        "official_evaluators": [
            {
                "id": evaluator.id,
                "command_id": evaluator.command_id,
                "kind": evaluator.kind,
                "required": evaluator.required,
                "cwd_sha256": _trusted_or_raw_hash(evaluator.cwd, evaluator.cwd_sha256),
                "command_sha256": _trusted_or_raw_hash(evaluator.command, evaluator.command_sha256),
                "timeout_seconds": evaluator.timeout_seconds,
                "expected_exit_codes": list(evaluator.expected_exit_codes),
            }
            for evaluator in boundary.official_evaluators
        ],
        "protected_surfaces": [
            {
                "path_sha256": _trusted_or_raw_hash(surface.path, surface.path_sha256),
                "reason_sha256": _trusted_or_raw_hash(surface.reason, surface.reason_sha256),
            }
            for surface in boundary.protected_surfaces
        ],
        "mutable_test_policy": boundary.mutable_test_policy,
        "allowed_test_paths_sha256": list(
            _trusted_or_raw_hashes(boundary.allowed_test_paths, boundary.allowed_test_paths_sha256)
        ),
        "denied_test_paths_sha256": list(
            _trusted_or_raw_hashes(boundary.denied_test_paths, boundary.denied_test_paths_sha256)
        ),
        "predicate_hash": boundary.predicate_hash,
        "contract_frozen_at": boundary.contract_frozen_at,
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _trusted_or_raw_hash(raw_value: str, stored_hash: str | None) -> str:
    """Prefer raw hashes unless storage had to redact or omit the raw value."""

    raw = str(raw_value)
    if stored_hash and "<REDACTED>" in raw:
        return stored_hash
    return _sha256_text(raw)


def _trusted_or_raw_hashes(raw_values: tuple[str, ...], stored_hashes: tuple[str, ...]) -> tuple[str, ...]:
    if not raw_values:
        return stored_hashes
    return tuple(
        _trusted_or_raw_hash(raw, stored_hashes[index] if index < len(stored_hashes) else None)
        for index, raw in enumerate(raw_values)
    )


def _field_state(source: dict[str, Any], key: str) -> str:
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


def _list_field_state(source: dict[str, Any], key: str) -> str:
    if key not in source:
        computed = "missing"
    else:
        items = _string_tuple(source.get(key))
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


def _expected_exit_codes(item: dict[str, Any]) -> tuple[int, ...]:
    if "expected_exit_codes" in item:
        value = item.get("expected_exit_codes")
        if isinstance(value, list | tuple):
            codes = tuple(int(code) for code in value)
            return codes or (0,)
    if "expected_exit_code" in item:
        return (int(item["expected_exit_code"]),)
    return (0,)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _dict_list(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _risk_tier_value(value: Any) -> str:
    try:
        return RiskTier(str(value)).value
    except ValueError:
        return RiskTier.C.value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _write_contract_text(path: Path, content: str) -> None:
    project_root = _project_root_for_ces_path(path)
    if project_root is not None:
        write_text_project_path(project_root, path, content)
        return
    if path.parent.exists() and path.parent.is_symlink():
        raise ValueError(f"Refusing to write through symlinked directory: {path.parent}")
    if path.exists() and path.is_symlink():
        raise ValueError(f"Refusing to write through symlinked file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError(f"Refusing to write completion contract through symlink: {path}")
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as handle:
        tmp_name = handle.name
        handle.write(content)
    os.replace(tmp_name, path)


def _project_root_for_ces_path(path: Path) -> Path | None:
    parts = path.parts
    if ".ces" not in parts:
        return None
    index = parts.index(".ces")
    if index == 0:
        return Path.cwd()
    return Path(*parts[:index])
