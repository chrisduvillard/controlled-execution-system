"""Structured completion contract for greenfield CES builds."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ces.shared.enums import RiskTier


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
    proof_binding_hash: str | None = None
    next_ces_command: str = "ces verify --json"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-native dictionary for durable CLI evidence."""

        return json.loads(json.dumps(asdict(self)))

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
            proof_binding_hash=str(payload["proof_binding_hash"])
            if isinstance(payload.get("proof_binding_hash"), str)
            else None,
            next_ces_command=str(payload.get("next_ces_command", "ces verify --json") or "ces verify --json"),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> CompletionContract:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def criteria_from_texts(texts: list[str] | tuple[str, ...]) -> tuple[AcceptanceCriterion, ...]:
    return tuple(
        AcceptanceCriterion(id=f"AC-{index:03d}", text=text.strip())
        for index, text in enumerate(texts, start=1)
        if text.strip()
    )


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


def _risk_tier_value(value: Any) -> str:
    try:
        return RiskTier(str(value)).value
    except ValueError:
        return RiskTier.C.value


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
