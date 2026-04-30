"""Observed Legacy Behavior model (MODEL-15).

Tracks behaviors observed in legacy/brownfield systems that agents
discover during code analysis. These observations go through a
disposition flow:

1. Pending (disposition=None): Just observed, not yet reviewed
2. Reviewed (disposition set): Human has decided to PRESERVE, CHANGE, or RETIRE
3. Promoted (promoted_to_prl_id set): Promoted to a PRL item

Also supports UNDER_INVESTIGATION and NEW dispositions.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ces.shared.enums import LegacyDisposition


class ObservedLegacyBehavior(BaseModel):
    """An observed behavior in a legacy system.

    Not frozen because disposition and review status change over time.

    Validators:
    - promoted_to_prl_id requires disposition to be set
    - discarded entries cannot be promoted
    """

    model_config = ConfigDict(strict=True)

    # Identity
    entry_id: str
    system: str

    # Observation
    behavior_description: str
    inferred_by: str
    inferred_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)

    # Disposition
    disposition: LegacyDisposition | None = None

    # Review
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    # Promotion to PRL
    promoted_to_prl_id: str | None = None

    # Discard
    discarded: bool = False

    @model_validator(mode="after")
    def validate_promotion_and_discard(self) -> ObservedLegacyBehavior:
        """Validate disposition flow constraints.

        - promoted_to_prl_id requires disposition to be set
        - discarded entries cannot have promoted_to_prl_id
        """
        if self.promoted_to_prl_id is not None and self.disposition is None:
            msg = "Cannot set promoted_to_prl_id without a disposition"
            raise ValueError(msg)
        if self.discarded and self.promoted_to_prl_id is not None:
            msg = "Discarded entries cannot be promoted (promoted_to_prl_id must be None)"
            raise ValueError(msg)
        return self
