"""Structured completion contract for greenfield CES builds."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
class CompletionContract:
    request: str
    project_type: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    inferred_commands: tuple[VerificationCommand, ...] = ()
    runtime: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CompletionContract:
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
