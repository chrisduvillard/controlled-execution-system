"""Schema-backed Intent Gate domain models."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from ces.execution.secrets import scrub_secrets_from_text
from ces.shared.base import CESBaseModel

IntentGateDecision = Literal["ask", "assume_and_proceed", "proceed", "blocked"]

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TEXT_LENGTH = 2000


def _clean_text(value: str, *, field_name: str) -> str:
    scrubbed = scrub_secrets_from_text(value)
    if scrubbed != value:
        msg = f"{field_name} contains secret-like content"
        raise ValueError(msg)
    cleaned = " ".join(_CONTROL_RE.sub(" ", value).split())
    if not cleaned:
        msg = f"{field_name} must not be blank"
        raise ValueError(msg)
    if len(cleaned) > _MAX_TEXT_LENGTH:
        msg = f"{field_name} must be {_MAX_TEXT_LENGTH} characters or fewer"
        raise ValueError(msg)
    return cleaned


def _stable_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class IntentQuestion(CESBaseModel):
    """A material clarification question for the Intent Gate."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    question: str
    why_it_matters: str
    default_if_unanswered: str | None = None
    materiality: str = "material"

    @field_validator("question", "why_it_matters", "materiality", "default_if_unanswered")
    @classmethod
    def validate_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _clean_text(value, field_name=info.field_name)


class SpecificationLedger(CESBaseModel):
    """Structured statement of understood user intent and execution boundaries."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    goal: str
    deliverable: str
    audience: str
    scope: tuple[str, ...] = ()
    non_goals: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    tool_permissions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[IntentQuestion, ...] = ()
    decisions: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    verification_plan: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    @field_validator("goal", "deliverable", "audience")
    @classmethod
    def validate_required_text(cls, value: str, info: Any) -> str:
        return _clean_text(value, field_name=info.field_name)

    @field_validator(
        "scope",
        "non_goals",
        "constraints",
        "inputs",
        "tool_permissions",
        "assumptions",
        "decisions",
        "acceptance_criteria",
        "verification_plan",
        "risks",
    )
    @classmethod
    def validate_text_tuple(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return tuple(_clean_text(item, field_name=info.field_name) for item in value)


class IntentGatePreflight(CESBaseModel):
    """Deterministic Intent Gate preflight decision and ledger."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    preflight_id: str | None = None
    decision: IntentGateDecision
    ledger: SpecificationLedger
    safe_next_step: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str | None = None

    @field_validator("preflight_id")
    @classmethod
    def validate_preflight_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"igp-[0-9a-f]{16}", value):
            msg = "preflight_id must match igp-<16 hex>"
            raise ValueError(msg)
        return value

    @field_validator("safe_next_step")
    @classmethod
    def validate_safe_next_step(cls, value: str) -> str:
        return _clean_text(value, field_name="safe_next_step")

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            msg = "content_hash must be a sha256 hex digest"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def populate_content_hash(self) -> IntentGatePreflight:
        payload = self.model_dump(mode="json", exclude={"preflight_id", "created_at", "content_hash"})
        digest = _stable_sha256(payload)
        if self.content_hash is not None and self.content_hash != digest:
            msg = "content_hash does not match preflight content"
            raise ValueError(msg)
        object.__setattr__(self, "content_hash", digest)
        if self.preflight_id is None:
            object.__setattr__(self, "preflight_id", f"igp-{digest[:16]}")
        elif self.preflight_id != f"igp-{digest[:16]}":
            msg = "preflight_id does not match content_hash prefix"
            raise ValueError(msg)
        return self
