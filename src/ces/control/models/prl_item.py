"""PRL Item model (PRD Part IV SS2.2).

Product Requirements Ledger items define individual requirements with
acceptance criteria, priority, and optional legacy disposition fields.
"""

from __future__ import annotations

from typing import Literal

from ces.shared.base import CESBaseModel, GovernedArtifactBase
from ces.shared.enums import (
    LegacyDisposition,
    Priority,
    PRLItemType,
    VerificationMethod,
)


class AcceptanceCriterion(CESBaseModel):
    """An acceptance criterion with its verification method."""

    criterion: str
    verification_method: VerificationMethod


class PRLItem(GovernedArtifactBase):
    """PRL Item truth artifact (PRD SS2.2).

    Represents a single product requirement with acceptance criteria,
    negative examples, and optional legacy fields for brownfield projects.
    Status: draft | approved | deferred | retired (via ArtifactStatus).
    """

    schema_type: Literal["prl_item"] = "prl_item"
    prl_id: str
    type: PRLItemType
    statement: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    negative_examples: tuple[str, ...]
    priority: Priority
    release_slice: str
    dependencies: tuple[str, ...] = ()

    # Optional legacy fields (PRD SS2.2 optional_fields)
    legacy_disposition: LegacyDisposition | None = None
    legacy_source_system: str | None = None
    legacy_golden_master_ref: str | None = None
    technical_debt_refs: tuple[str, ...] = ()
