"""Vision Anchor model (PRD Part IV SS2.1).

The Vision Anchor captures the product vision and constraints that all work
must align to. It is the highest-level truth artifact in the CES hierarchy.
"""

from __future__ import annotations

from typing import Literal

from ces.shared.base import CESBaseModel, GovernedArtifactBase


class TargetUser(CESBaseModel):
    """A target user segment for the product."""

    segment: str
    description: str


class HardConstraint(CESBaseModel):
    """An immovable boundary that the product must respect."""

    constraint: str
    source: str


class KillCriterion(CESBaseModel):
    """A condition under which the project should stop."""

    criterion: str
    measurement: str


class VisionAnchor(GovernedArtifactBase):
    """Vision Anchor truth artifact (PRD SS2.1).

    Captures the product vision, target users, constraints, and kill criteria.
    Status: draft | approved | superseded (via ArtifactStatus).
    MODEL-16: Approved requires signature (inherited from GovernedArtifactBase).
    """

    schema_type: Literal["vision_anchor"] = "vision_anchor"
    anchor_id: str
    target_users: tuple[TargetUser, ...]
    problem_statement: str
    intended_value: str
    non_goals: tuple[str, ...]
    experience_expectations: tuple[str, ...]
    hard_constraints: tuple[HardConstraint, ...]
    kill_criteria: tuple[KillCriterion, ...]
