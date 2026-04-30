"""Review assignment models (D-05, D-06) -- reviewer roles and independence.

ReviewerRole defines the three reviewer types in the Adversarial Review Triad.
ReviewAssignment assigns a specific model/agent to a reviewer role.
IndependenceViolation captures violations of agent independence rules.
"""

from __future__ import annotations

from enum import Enum

from ces.shared.base import CESBaseModel


class ReviewerRole(str, Enum):
    """Reviewer roles in the Adversarial Review Triad (D-05).

    Three distinct review perspectives:
    - STRUCTURAL: Code structure, architecture, patterns
    - SEMANTIC: Business logic, correctness, edge cases
    - RED_TEAM: Security, adversarial scenarios, abuse potential
    """

    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    RED_TEAM = "red_team"


class ReviewAssignment(CESBaseModel):
    """Assignment of a reviewer to a specific role (D-05).

    Frozen CESBaseModel: assignments are immutable once made.
    The review router creates these and passes them to review executors.
    """

    role: ReviewerRole
    model_id: str
    agent_id: str


class IndependenceViolation(CESBaseModel):
    """Record of an agent independence violation (D-06).

    Captures when reviewer independence rules are broken:
    - Self-review: agent reviews its own output
    - Model overlap: two reviewers share the same model
    """

    violation_type: str
    details: str
