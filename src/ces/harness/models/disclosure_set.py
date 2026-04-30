"""DisclosureSet model (D-04) -- mandatory adversarial honesty disclosures.

Captures retries, skipped checks, summarized context, and disagreements
as frozen fields. Every evidence packet must include a DisclosureSet
to ensure agents honestly report their process.
"""

from __future__ import annotations

from ces.shared.base import CESBaseModel


class DisclosureSet(CESBaseModel):
    """Mandatory disclosure fields for adversarial honesty (D-04).

    Frozen CESBaseModel: once created, disclosures cannot be altered.
    This ensures the adversarial honesty record is tamper-proof.

    Fields:
        retries_used: Number of retry attempts consumed.
        skipped_checks: List of check IDs that were skipped.
        summarized_context: Whether context was summarized/truncated.
        summarization_details: Details about how context was summarized.
        disagreements: List of reviewer disagreement descriptions.
    """

    retries_used: int
    skipped_checks: tuple[str, ...]
    summarized_context: bool
    summarization_details: str | None = None
    disagreements: tuple[str, ...]
