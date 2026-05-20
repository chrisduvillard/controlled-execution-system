"""Explicit control-plane readiness status for builder workflows."""

from __future__ import annotations

from enum import Enum

from pydantic import field_validator

from ces.shared.base import CESBaseModel


class GovernanceState(str, Enum):
    """Operator-facing governance state after triage and sensor policy."""

    CLEAR = "clear"
    ADVISORY_YELLOW = "advisory_yellow"
    BLOCKING_RED = "blocking_red"
    NOT_CONFIGURED = "not_configured"


class ControlPlaneStatus(CESBaseModel):
    """Separates code completion, verification, governance, and ship readiness."""

    code_completed: bool
    acceptance_verified: bool
    governance_state: GovernanceState
    approval_decision: str | None = None
    merge_allowed: bool | None = None
    merge_not_applied: bool = False
    blocking_reasons: tuple[str, ...] = ()

    @field_validator("blocking_reasons", mode="before")
    @classmethod
    def _coerce_blocking_reasons(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, tuple):
            return tuple(str(item) for item in value)
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        return (str(value),)

    @property
    def governance_clear(self) -> bool:
        """Whether governance is clear enough to allow ready-to-ship messaging."""

        return self.governance_state in {GovernanceState.CLEAR, GovernanceState.NOT_CONFIGURED}

    @property
    def ready_to_ship(self) -> bool:
        """True only when every control-plane layer is clear."""

        return (
            self.code_completed
            and self.acceptance_verified
            and self.governance_clear
            and self.approval_decision == "approve"
            and self.merge_allowed is not False
            and not self.merge_not_applied
            and not self.blocking_reasons
        )

    @property
    def needs_review(self) -> bool:
        """Whether a human/operator still needs to review or recover the run."""

        return not self.ready_to_ship

    @property
    def summary_outcome(self) -> str:
        """Stable human summary used by CLI completion panels."""

        if self.approval_decision != "approve":
            return "held for another pass"
        if not self.code_completed:
            return "approved, but runtime did not complete"
        if not self.acceptance_verified:
            return "approved, but acceptance verification is blocked"
        if self.governance_state == GovernanceState.BLOCKING_RED:
            return "approved, but governance is blocked"
        if self.blocking_reasons:
            return "approved, but blocking issues remain"
        if self.merge_allowed is False and self.merge_not_applied:
            return "approved, but merge was not applied"
        if self.merge_allowed is False:
            return "approved, but merge is blocked"
        if self.governance_state == GovernanceState.ADVISORY_YELLOW:
            return "approved, but governance needs review"
        return "ready to ship"
