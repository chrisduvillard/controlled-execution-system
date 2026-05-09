"""Verification profile model and loader.

Profiles live at ``.ces/verification-profile.json`` in the project root and
record whether common verification checks are required, optional, advisory, or
unavailable for that specific project.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import field_validator

from ces.shared.base import CESBaseModel

PROFILE_RELATIVE_PATH = Path(".ces") / "verification-profile.json"


class VerificationStatus(str, Enum):
    """Known requirement levels for a verification check."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    ADVISORY = "advisory"
    UNAVAILABLE = "unavailable"


class VerificationCheck(CESBaseModel):
    """Requirement metadata for a single verification check."""

    status: VerificationStatus
    configured: bool
    reason: str

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> VerificationStatus:
        if isinstance(value, VerificationStatus):
            return value
        if isinstance(value, str):
            return VerificationStatus(value)
        msg = "status must be a verification status string"
        raise TypeError(msg)

    @property
    def required(self) -> bool:
        """Return whether this check should block when evidence is missing."""
        return self.status is VerificationStatus.REQUIRED


class VerificationProfile(CESBaseModel):
    """Project-specific verification requirements."""

    version: int = 1
    checks: dict[str, VerificationCheck]

    def requirement_for(self, check_name: str) -> VerificationCheck:
        """Return requirement metadata for ``check_name``.

        Unknown checks are treated as required to preserve existing strict
        behavior when an explicitly-run sensor lacks profile guidance.
        """
        check = self.checks.get(check_name)
        if check is not None:
            return check
        return VerificationCheck(
            status=VerificationStatus.REQUIRED,
            configured=True,
            reason=f"No verification profile entry for {check_name}; preserving strict behavior",
        )

    def is_required(self, check_name: str) -> bool:
        """Return whether ``check_name`` is required by this profile."""
        return self.requirement_for(check_name).required

    def to_json(self) -> str:
        """Serialize profile as pretty JSON with a trailing newline."""
        return self.model_dump_json(indent=2) + "\n"


def profile_path(project_root: str | Path) -> Path:
    """Return the verification profile path for ``project_root``."""
    return Path(project_root) / PROFILE_RELATIVE_PATH


def load_verification_profile(project_root: str | Path) -> VerificationProfile | None:
    """Load ``.ces/verification-profile.json`` if present.

    Invalid JSON or schema errors are allowed to propagate: a corrupt profile is
    actionable project configuration, not an absent profile.
    """
    path = profile_path(project_root)
    if not path.is_file():
        return None
    return VerificationProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
