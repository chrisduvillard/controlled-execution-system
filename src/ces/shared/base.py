"""Base models for CES governed artifacts and domain objects.

GovernedArtifactBase enforces governance rules: approved artifacts must be signed (MODEL-16).
CESBaseModel provides a strict, frozen base for non-governed domain models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ces.shared.enums import ArtifactStatus


class GovernedArtifactBase(BaseModel):
    """Base model for all truth artifacts subject to governance controls.

    Enforces:
    - version >= 1
    - Approved artifacts must have a signature (MODEL-16)
    """

    version: int = Field(ge=1)
    status: ArtifactStatus
    owner: str
    created_at: datetime
    last_confirmed: datetime
    signature: str | None = None
    content_hash: str | None = None

    model_config = ConfigDict(strict=True, frozen=True)

    @model_validator(mode="after")
    def approved_requires_signature(self) -> GovernedArtifactBase:
        """Approved artifacts must be signed (MODEL-16)."""
        if self.status == ArtifactStatus.APPROVED and self.signature is None:
            msg = "Approved artifacts must be signed"
            raise ValueError(msg)
        return self


class CESBaseModel(BaseModel):
    """Base model for non-governed CES domain objects.

    Strict mode prevents coercion; frozen makes instances immutable.
    """

    model_config = ConfigDict(strict=True, frozen=True)
