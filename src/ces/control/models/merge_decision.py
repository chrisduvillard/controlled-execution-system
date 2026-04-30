"""Merge decision model for pre-merge validation results.

Exports:
    MergeCheck: Individual validation check result (frozen dataclass).
    MergeDecision: Aggregate merge validation decision (frozen dataclass).

The MergeController produces a MergeDecision containing ALL individual
MergeCheck results, enabling callers to see exactly which checks passed
or failed (Pitfall 6: no partial validation).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MergeCheck:
    """Result of a single pre-merge validation check.

    Attributes:
        name: Check identifier (e.g., "evidence_exists", "manifest_fresh").
        passed: True if the check passed, False if it failed.
        detail: Human-readable explanation of the result.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class MergeDecision:
    """Aggregate result of all pre-merge validation checks.

    Attributes:
        allowed: True if merge can proceed (all checks passed).
        checks: List of all individual check results in defined order.
        reason: Summary reason for blocking (empty if allowed).
    """

    allowed: bool
    checks: tuple[MergeCheck, ...] = field(default_factory=tuple)
    reason: str = ""
