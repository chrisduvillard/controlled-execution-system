"""Structured reports for harness evolution trajectory distillation."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, ValidationInfo, field_validator

from ces.execution.secrets import scrub_secrets_from_text
from ces.shared.base import CESBaseModel

TrajectoryOutcome = Literal["pass", "fail", "unknown"]


_TEXT_LIST_FIELDS = {
    "validation_commands_observed",
    "proxy_validation_warnings",
    "evidence_pointers",
}


def _reject_secret_like_text(value: str, field_name: str) -> str:
    scrubbed = scrub_secrets_from_text(value)
    if scrubbed != value:
        raise ValueError(f"{field_name} contains secret-looking content")
    return value


def _clean_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return _reject_secret_like_text(value, field_name)


class TrajectoryReport(CESBaseModel):
    """Small structured summary of a runtime/dogfood trajectory.

    The report intentionally stores pointers and classified observations, not
    the raw transcript body.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    task_run_id: str | None = None
    outcome: TrajectoryOutcome = "unknown"
    failure_class: str = "unknown"
    suspected_root_cause: str = "insufficient evidence"
    validation_commands_observed: list[str] = Field(default_factory=list)
    proxy_validation_warnings: list[str] = Field(default_factory=list)
    evidence_pointers: list[str] = Field(default_factory=list)

    @field_validator("task_run_id", "failure_class", "suspected_root_cause")
    @classmethod
    def _validate_optional_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _clean_optional_text(value, info.field_name)

    @field_validator(*_TEXT_LIST_FIELDS)
    @classmethod
    def _validate_text_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        for item in value:
            if not item.strip():
                raise ValueError(f"{info.field_name} must not contain empty entries")
            _reject_secret_like_text(item, info.field_name)
        return value

    def to_markdown(self) -> str:
        """Render a compact markdown report without embedding raw transcript text."""

        lines = ["# Harness trajectory report", ""]
        lines.append(f"- task/run id: {self.task_run_id or 'unknown'}")
        lines.append(f"- outcome: {self.outcome}")
        lines.append(f"- failure class: {self.failure_class}")
        lines.append(f"- suspected root cause: {self.suspected_root_cause}")
        lines.append("")
        lines.extend(_markdown_list("Validation commands observed", self.validation_commands_observed))
        lines.extend(_markdown_list("Proxy-validation warnings", self.proxy_validation_warnings))
        lines.extend(_markdown_list("Evidence pointers", self.evidence_pointers))
        return "\n".join(lines).rstrip() + "\n"


def _markdown_list(title: str, values: list[str]) -> list[str]:
    lines = [f"## {title}"]
    if not values:
        lines.append("- none")
    else:
        lines.extend(f"- {value}" for value in values)
    lines.append("")
    return lines
