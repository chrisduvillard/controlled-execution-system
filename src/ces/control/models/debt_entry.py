"""Technical Debt Register Entry model (PRD Part IV SS2.8).

Tracks technical debt with origin, severity, resolution plans,
and optional legacy system references.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import model_validator

from ces.shared.base import CESBaseModel
from ces.shared.enums import DebtOriginType, DebtSeverity, DebtStatus


class DebtEntry(CESBaseModel):
    """Technical Debt Register Entry (PRD SS2.8).

    Tracks a single technical debt item. Non-inherited debt must have
    a resolution_plan_ref and resolution_deadline.
    """

    debt_id: str
    origin_type: DebtOriginType
    description: str
    affected_artifacts: tuple[str, ...]
    affected_task_classes: tuple[str, ...]
    severity: DebtSeverity
    owner: str
    resolution_plan_ref: str | None = None
    resolution_deadline: date | None = None
    accepting_approver: str
    created_at: datetime
    status: DebtStatus

    # Optional legacy fields
    legacy_source_system: str | None = None
    related_prl_items: tuple[str, ...] = ()
    related_migration_pack: str | None = None

    @model_validator(mode="after")
    def non_inherited_requires_resolution(self) -> DebtEntry:
        """Non-inherited debt must have resolution plan and deadline."""
        if self.origin_type != DebtOriginType.INHERITED:
            if self.resolution_plan_ref is None:
                raise ValueError(f"Non-inherited debt ({self.origin_type.value}) requires resolution_plan_ref")
            if self.resolution_deadline is None:
                raise ValueError(f"Non-inherited debt ({self.origin_type.value}) requires resolution_deadline")
        return self
