"""Knowledge Vault Note model (MODEL-14).

The Knowledge Vault is a Zettelkasten-based knowledge store.
VaultNote represents a single note with:
- Category (one of 9 categories)
- Trust level (verified, agent-inferred, stale-risk)
- Content and metadata
- Invalidation trigger support

The Knowledge Vault is informational only -- it must NEVER answer
requirement, policy, or risk-acceptance questions.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ces.shared.enums import VaultCategory, VaultTrustLevel


class VaultNote(BaseModel):
    """A note in the Knowledge Vault (Zettelkasten).

    Not frozen because content and trust_level may be updated.
    For example, a note may transition from AGENT_INFERRED to
    VERIFIED after human review, or to STALE_RISK when its
    source data changes.
    """

    model_config = ConfigDict(strict=True)

    # Identity
    note_id: str

    # Classification
    category: VaultCategory
    trust_level: VaultTrustLevel

    # Content
    content: str
    source: str

    # Timestamps
    created_at: datetime
    updated_at: datetime

    # Metadata
    tags: tuple[str, ...] = ()
    related_artifacts: tuple[str, ...] = ()

    # Invalidation
    invalidation_trigger: str | None = None
