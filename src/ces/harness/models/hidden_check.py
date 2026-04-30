"""Hidden check models for undisclosed verification test injection.

Implements TRUST-05 (hidden check injection) data structures.
Both models are frozen dataclasses to ensure immutability of check
definitions and recorded results (threat mitigation T-02-14).

HiddenCheck: Defines a single verification test in the hidden check pool.
HiddenCheckResult: Records the outcome of a hidden check for a specific profile.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HiddenCheck:
    """A single undisclosed verification test in the hidden check pool.

    Frozen to prevent mutation after creation. Checks are authored by humans
    or a separate agent and stored in a sealed pool accessible only to the
    HiddenCheckEngine.

    Attributes:
        check_id: Unique identifier for this check.
        description: Human-readable description of what the check verifies.
        expected_outcome: The expected result string for a passing check.
        pool_generation: Which rotation cycle this check was added in.
    """

    check_id: str
    description: str
    expected_outcome: str
    pool_generation: int


@dataclass(frozen=True)
class HiddenCheckResult:
    """Recorded outcome of a hidden check for a specific harness profile.

    Frozen to prevent post-recording tampering (threat mitigation T-02-14).

    Attributes:
        check_id: The check that was executed.
        profile_id: The harness profile that was tested.
        passed: Whether the agent passed this hidden check.
        checked_at: ISO 8601 timestamp of when the check was performed.
    """

    check_id: str
    profile_id: str
    passed: bool
    checked_at: str
