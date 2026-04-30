"""Architecture Blueprint model (PRD Part IV SS2.3).

Defines the system architecture with components, trust boundaries,
non-functional requirements, and prohibited patterns.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from ces.shared.base import CESBaseModel, GovernedArtifactBase
from ces.shared.enums import NFRCategory, Sensitivity


class ComponentBoundaries(CESBaseModel):
    """Allowed and prohibited dependencies for a component."""

    allowed_dependencies: tuple[str, ...]
    prohibited_dependencies: tuple[str, ...]


class DataFlow(CESBaseModel):
    """A data flow between components with sensitivity classification.

    Uses from_component instead of 'from' since 'from' is a Python keyword.
    """

    model_config = ConfigDict(strict=True, frozen=True, populate_by_name=True)

    from_component: str = Field(alias="from")
    to: str
    data_type: str
    sensitivity: Sensitivity


class StateOwnership(CESBaseModel):
    """State ownership declaration for a component.

    Uses owner_component_id instead of 'owner' to avoid shadowing
    GovernedArtifactBase.owner when used in nested contexts.
    """

    state_name: str
    owner_component_id: str = Field(alias="owner")

    model_config = ConfigDict(strict=True, frozen=True, populate_by_name=True)


class Component(CESBaseModel):
    """A system component with boundaries, data flows, and state ownership."""

    component_id: str
    name: str
    responsibility: str
    boundaries: ComponentBoundaries
    data_flows: tuple[DataFlow, ...]
    state_ownership: tuple[StateOwnership, ...]


class TrustBoundary(CESBaseModel):
    """A trust boundary separating inside and outside components."""

    boundary_id: str
    inside: tuple[str, ...]
    outside: tuple[str, ...]
    crossing_rules: str


class NFRequirement(CESBaseModel):
    """A non-functional requirement with category and measurement."""

    nfr_id: str
    category: NFRCategory
    requirement: str
    measurement: str


class ProhibitedPattern(CESBaseModel):
    """A pattern that is explicitly prohibited with rationale."""

    pattern: str
    reason: str


class ArchitectureBlueprint(GovernedArtifactBase):
    """Architecture Blueprint truth artifact (PRD SS2.3).

    Defines system components, trust boundaries, NFRs, and prohibited patterns.
    Status: draft | approved | superseded (via ArtifactStatus).
    """

    schema_type: Literal["architecture_blueprint"] = "architecture_blueprint"
    blueprint_id: str
    components: tuple[Component, ...]
    trust_boundaries: tuple[TrustBoundary, ...]
    non_functional_requirements: tuple[NFRequirement, ...]
    prohibited_patterns: tuple[ProhibitedPattern, ...]
