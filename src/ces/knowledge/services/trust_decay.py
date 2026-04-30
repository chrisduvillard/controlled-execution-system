"""Trust level auto-decay logic for knowledge vault notes (VAULT-02).

Agent-inferred notes decay to stale-risk after configurable per-category
thresholds. Verified notes NEVER decay automatically -- they maintain
their trust level until explicitly changed by a human.

Threat mitigations:
- T-05-14: Decay thresholds set at construction time, not modifiable at runtime.
           Decay only downgrades trust (agent-inferred -> stale-risk), never upgrades.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ces.shared.enums import ActorType, VaultCategory, VaultTrustLevel

# Default decay thresholds in days per category.
# Agent-inferred notes older than this are transitioned to stale-risk.
_DEFAULT_DECAY_THRESHOLDS: dict[str, int] = {
    "decisions": 90,
    "patterns": 60,
    "escapes": 30,
    "discovery": 30,
    "calibration": 45,
    "harness": 60,
    "domain": 90,
    "stakeholders": 90,
    "sessions": 14,
}


class TrustDecayManager:
    """Manages automatic trust decay for knowledge vault notes.

    Transitions agent-inferred notes to stale-risk after per-category
    thresholds expire. Verified notes are NEVER decayed automatically.

    Args:
        repository: VaultRepository for DB access.
        audit_ledger: Audit ledger for logging decay events.
        decay_thresholds: Optional custom thresholds (category -> days).
            Merges with defaults, so you only need to specify overrides.
    """

    def __init__(
        self,
        repository: object | None = None,
        audit_ledger: object | None = None,
        decay_thresholds: dict[str, int] | None = None,
    ) -> None:
        self._repository = repository
        self._audit_ledger = audit_ledger
        self._thresholds = dict(_DEFAULT_DECAY_THRESHOLDS)
        if decay_thresholds is not None:
            self._thresholds.update(decay_thresholds)

    async def decay_stale_notes(self) -> list[str]:
        """Run decay for all categories, transitioning stale notes.

        For each category, computes the threshold datetime and queries
        for agent-inferred notes older than that threshold. Updates each
        to stale-risk trust level.

        IMPORTANT: This does NOT decay VERIFIED notes. Verified notes
        maintain their trust level until explicitly changed by a human.

        Returns:
            List of note IDs that were decayed.
        """
        if self._repository is None:
            return []

        decayed: list[str] = []
        now = datetime.now(timezone.utc)

        for category in VaultCategory:
            threshold_days = self._thresholds.get(
                category.value,
                _DEFAULT_DECAY_THRESHOLDS.get(category.value, 30),
            )
            threshold_dt = now - timedelta(days=threshold_days)

            rows = await self._repository.get_by_category(category.value)

            for row in rows:
                # Only decay AGENT_INFERRED notes
                if row.trust_level != VaultTrustLevel.AGENT_INFERRED.value:
                    continue

                updated_at = getattr(row, "updated_at", None)
                if updated_at is None:
                    continue

                if updated_at < threshold_dt:
                    updated = await self._repository.update_trust_level(
                        row.note_id,
                        VaultTrustLevel.STALE_RISK.value,
                    )
                    if updated is not None:
                        decayed.append(row.note_id)

                        if self._audit_ledger is not None:
                            await self._audit_ledger.record_truth_change(
                                artifact_id=row.note_id,
                                actor="trust_decay_manager",
                                actor_type=ActorType.CONTROL_PLANE,
                                action_summary=(
                                    f"Vault note {row.note_id} decayed from "
                                    f"agent-inferred to stale-risk "
                                    f"(category: {category.value}, "
                                    f"threshold: {threshold_days} days)"
                                ),
                            )

        return decayed

    def get_decay_thresholds(self) -> dict[str, int]:
        """Return current decay thresholds.

        Returns:
            Dict mapping category name to decay threshold in days.
        """
        return dict(self._thresholds)
