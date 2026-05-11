"""Pydantic models for local harness evolution change manifests."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from ces.execution.secrets import scrub_secrets_from_text
from ces.shared.base import CESBaseModel


class HarnessComponentType(StrEnum):
    """Explicit harness component classes that can be evolved locally."""

    SYSTEM_PROMPT = "system_prompt"
    TOOL_DESCRIPTION = "tool_description"
    TOOL_POLICY = "tool_policy"
    MIDDLEWARE = "middleware"
    SKILL = "skill"
    SUBAGENT = "subagent"
    MEMORY = "memory"
    RUNTIME_PROFILE = "runtime_profile"


HarnessChangeStatus = Literal["draft", "proposed", "active", "superseded", "rolled_back"]


_TEXT_FIELDS = {
    "title",
    "failure_pattern",
    "root_cause_hypothesis",
    "rollback_condition",
}
_LIST_TEXT_FIELDS = {
    "files_changed",
    "evidence_refs",
    "predicted_fixes",
    "predicted_regressions",
    "validation_plan",
}


def _reject_secret_like_text(value: str, field_name: str) -> str:
    scrubbed = scrub_secrets_from_text(value)
    if scrubbed != value:
        msg = f"{field_name} contains secret-looking content"
        raise ValueError(msg)
    return value


def _reject_blank_text(value: str, field_name: str) -> str:
    if not value.strip():
        msg = f"{field_name} must not be empty"
        raise ValueError(msg)
    return value


class HarnessChangeManifest(CESBaseModel):
    """Falsifiable manifest for a proposed harness component change."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    change_id: str = Field(pattern=r"^hchg-[a-zA-Z0-9_.:-]+$")
    title: str
    component_type: HarnessComponentType
    files_changed: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    failure_pattern: str
    root_cause_hypothesis: str
    predicted_fixes: list[str] = Field(default_factory=list)
    predicted_regressions: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)
    rollback_condition: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: HarnessChangeStatus = "draft"

    @field_validator("component_type", mode="before")
    @classmethod
    def _parse_component_type(cls, value: object) -> object:
        if isinstance(value, str):
            return HarnessComponentType(value)
        return value

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: object) -> object:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @field_validator(*_TEXT_FIELDS)
    @classmethod
    def _validate_text(cls, value: str, info: ValidationInfo) -> str:
        value = _reject_blank_text(value, info.field_name)
        return _reject_secret_like_text(value, info.field_name)

    @field_validator(*_LIST_TEXT_FIELDS)
    @classmethod
    def _validate_text_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        for item in value:
            _reject_blank_text(item, info.field_name)
            _reject_secret_like_text(item, info.field_name)
        return value

    @field_validator("change_id")
    @classmethod
    def _validate_change_id(cls, value: str) -> str:
        _reject_secret_like_text(value, "change_id")
        return value

    @model_validator(mode="after")
    def _require_predictions(self) -> HarnessChangeManifest:
        if not self.predicted_fixes:
            raise ValueError("predicted_fixes must contain at least one falsifiable expected fix")
        if not self.predicted_regressions:
            raise ValueError("predicted_regressions must contain at least one regression risk")
        if not self.validation_plan:
            raise ValueError("validation_plan must contain at least one validation step")
        return self
