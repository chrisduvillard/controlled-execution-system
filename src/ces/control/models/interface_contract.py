"""Interface Contract model (PRD Part IV SS2.4).

Defines contracts between system components including interface type,
versioning rules, compatibility guarantees, and impact scope.
"""

from __future__ import annotations

from typing import Literal

from ces.shared.base import GovernedArtifactBase
from ces.shared.enums import (
    CompatibilityRule,
    ImpactScope,
    InterfaceType,
    VersioningRule,
)


class InterfaceContract(GovernedArtifactBase):
    """Interface Contract truth artifact (PRD SS2.4).

    Defines a contract between a producer and its consumers, including
    interface type, schema reference, versioning, and compatibility rules.
    Status: draft | approved | deprecated | retired (via ArtifactStatus/ContractStatus).
    """

    schema_type: Literal["interface_contract"] = "interface_contract"
    contract_id: str
    producer: str
    consumers: tuple[str, ...]
    interface_type: InterfaceType
    schema_ref: str
    versioning_rule: VersioningRule
    compatibility_rule: CompatibilityRule
    impact_scope: ImpactScope
