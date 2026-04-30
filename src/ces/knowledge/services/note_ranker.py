"""Note ranker for tier-based guide pack selection (VAULT-05).

Selects and ranks knowledge vault notes for inclusion in guide packs.
Tier-based limits ensure higher-risk tiers get fewer, more relevant notes:
- Tier A (highest risk): max 3 notes
- Tier B (medium risk): max 5 notes
- Tier C (lowest risk): max 10 notes

Scoring combines trust weight, tag overlap, and recency bonus to
surface the most relevant and trustworthy notes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ces.control.models.knowledge_vault import VaultNote
from ces.shared.enums import RiskTier, VaultTrustLevel


class NoteRanker:
    """Ranks and selects vault notes for guide pack assembly.

    Uses a scoring system that combines:
    - Trust weight: VERIFIED > AGENT_INFERRED; STALE_RISK excluded
    - Tag overlap: More matching tags = higher score
    - Recency bonus: Newer notes get a small boost (linear decay over 1 year)
    """

    # Maximum notes per risk tier for guide pack inclusion
    TIER_LIMITS: dict[RiskTier, int] = {
        RiskTier.C: 10,
        RiskTier.B: 5,
        RiskTier.A: 3,
    }

    # Trust level scoring weights
    TRUST_WEIGHTS: dict[VaultTrustLevel, float] = {
        VaultTrustLevel.VERIFIED: 3.0,
        VaultTrustLevel.AGENT_INFERRED: 1.5,
        VaultTrustLevel.STALE_RISK: 0.0,
    }

    @staticmethod
    def rank_notes(
        notes: list[VaultNote],
        relevance_tags: list[str],
    ) -> list[VaultNote]:
        """Rank notes by relevance score, excluding stale-risk.

        Scoring formula per note:
            trust_score = TRUST_WEIGHTS[note.trust_level]
            tag_overlap = count of matching tags
            recency_bonus = max(0, 1.0 - days_since_update / 365.0)
            total = trust_score + tag_overlap * 1.0 + recency_bonus * 0.5

        Args:
            notes: List of VaultNote instances to rank.
            relevance_tags: Tags to match against for relevance scoring.

        Returns:
            Sorted list of VaultNote, highest score first.
            Stale-risk notes are excluded.
        """
        # Filter out stale-risk notes (weight == 0.0)
        active_notes = [n for n in notes if NoteRanker.TRUST_WEIGHTS.get(n.trust_level, 0.0) > 0.0]

        now = datetime.now(timezone.utc)
        tag_set = set(relevance_tags)

        def _score(note: VaultNote) -> float:
            trust_score = NoteRanker.TRUST_WEIGHTS.get(note.trust_level, 0.0)
            tag_overlap = len(set(note.tags) & tag_set)
            recency_days = (now - note.updated_at).days
            recency_bonus = max(0.0, 1.0 - recency_days / 365.0)
            return trust_score + tag_overlap * 1.0 + recency_bonus * 0.5

        active_notes.sort(key=_score, reverse=True)
        return active_notes

    @staticmethod
    def select_for_tier(
        notes: list[VaultNote],
        tier: RiskTier,
        relevance_tags: list[str],
    ) -> list[VaultNote]:
        """Select notes for a specific risk tier with limit enforcement.

        Ranks notes by relevance, then truncates to the tier limit.

        Args:
            notes: List of VaultNote instances to select from.
            tier: The risk tier determining the note limit.
            relevance_tags: Tags for relevance scoring.

        Returns:
            Top-ranked notes up to the tier limit.
        """
        ranked = NoteRanker.rank_notes(notes, relevance_tags)
        limit = NoteRanker.TIER_LIMITS.get(tier, 10)
        return ranked[:limit]
