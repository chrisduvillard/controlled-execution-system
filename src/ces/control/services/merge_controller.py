"""Merge controller service with multi-check pre-merge validation.

Implements:
- MERGE-01: Blocks merge without valid evidence packet
- MERGE-02: Enforces tier-specific gate types (AGENT/HYBRID/HUMAN)
- MERGE-03: Validates manifest freshness, evidence completeness, approval
- D-09: Five explicit, enumerable, individually testable checks
- T-02-17: Evidence hash integrity validation
- T-02-18: Gate type ordering enforcement (HUMAN > HYBRID > AGENT)
- T-02-19: Audit logging for every merge decision
- T-02-20: Kill switch check runs first and is not skippable

The controller runs ALL checks without short-circuiting (Pitfall 6),
returning a MergeDecision with the complete list of check results.

Exports:
    MERGE_CHECKS: Ordered list of check names.
    MergeController: Service class for pre-merge validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ces.control.models.merge_decision import MergeCheck, MergeDecision
from ces.control.services.evidence_integrity import (
    compute_reviewed_evidence_hash,
    extract_evidence_manifest_hash,
    extract_reviewed_evidence_hash,
)
from ces.shared.enums import ActorType, BehaviorConfidence, EventType, GateType, RiskTier

if TYPE_CHECKING:
    from ces.control.services.kill_switch import KillSwitchProtocol

# ---------------------------------------------------------------------------
# Check names in evaluation order (D-09)
# ---------------------------------------------------------------------------

MERGE_CHECKS: list[str] = [
    "kill_switch_clear",
    "evidence_exists",
    "manifest_fresh",
    "gate_type_met",
    "review_complete",
]

# Gate type strictness ordering: HUMAN (3) > HYBRID (2) > AGENT (1)
# Higher number = more restrictive
_GATE_STRICTNESS: dict[GateType, int] = {
    GateType.AGENT: 1,
    GateType.HYBRID: 2,
    GateType.HUMAN: 3,
}


def _coerce_risk_tier(value: object) -> RiskTier:
    primitive = getattr(value, "value", value)
    return RiskTier(str(primitive))


def _coerce_behavior_confidence(value: object) -> BehaviorConfidence:
    primitive = getattr(value, "value", value)
    return BehaviorConfidence(str(primitive))


def _minimum_gate_for_manifest(manifest_risk_tier: object, manifest_bc: object) -> GateType:
    risk_tier = _coerce_risk_tier(manifest_risk_tier)
    behavior_confidence = _coerce_behavior_confidence(manifest_bc)
    if risk_tier == RiskTier.A or behavior_confidence == BehaviorConfidence.BC3:
        return GateType.HUMAN
    if risk_tier == RiskTier.B:
        return GateType.HYBRID
    return GateType.AGENT


class MergeController:
    """Pre-merge validation service enforcing all merge preconditions.

    Runs 5 explicit checks in order without short-circuiting, collecting
    all results into a MergeDecision. This ensures callers see the full
    picture of what passed and what failed (Pitfall 6 prevention).

    Args:
        kill_switch: Optional KillSwitchProtocol for merge halt checks.
            When None, the kill_switch_clear check always passes.
        gate_evaluator: Optional GateEvaluator (reserved for future use).
        audit_ledger: Optional audit ledger for MERGE event logging.
            Must have an async append_event method.
    """

    def __init__(
        self,
        kill_switch: KillSwitchProtocol | None = None,
        gate_evaluator: object | None = None,
        audit_ledger: object | None = None,
    ) -> None:
        self._kill_switch = kill_switch
        self._gate_evaluator = gate_evaluator
        self._audit_ledger = audit_ledger

    async def validate_merge(
        self,
        manifest_id: str,
        manifest_expires_at: datetime,
        manifest_content_hash: str,
        manifest_risk_tier: str,
        manifest_bc: str,
        evidence_packet: dict | None,
        evidence_manifest_hash: str | None,
        required_gate_type: GateType,
        actual_gate_type: GateType,
        review_sub_state: str,
        workflow_state: str,
    ) -> MergeDecision:
        """Validate all pre-merge conditions.

        Runs ALL 5 checks and collects results (no short-circuit per D-09).
        Logs a MERGE event to the audit ledger regardless of outcome (T-02-19).

        Args:
            manifest_id: Identifier of the manifest being merged.
            manifest_expires_at: Manifest expiry timestamp (UTC).
            manifest_content_hash: SHA-256 hash of manifest content.
            manifest_risk_tier: Risk tier string (e.g., "A", "B", "C").
            manifest_bc: Behavior confidence string (e.g., "BC1").
            evidence_packet: Evidence dict or None if missing.
            evidence_manifest_hash: Hash from evidence packet linking to manifest.
            required_gate_type: Gate type required by the evaluation.
            actual_gate_type: Gate type of the actual approval received.
            review_sub_state: Current review sub-state string.
            workflow_state: Current workflow state string.

        Returns:
            MergeDecision with allowed=True only if all 5 checks pass.
        """
        checks: list[MergeCheck] = []

        # Check 1: Kill switch (T-02-20: first check, not skippable)
        checks.append(self._check_kill_switch())

        # Check 2: Evidence exists and matches manifest (T-02-17)
        checks.append(self._check_evidence_exists(evidence_packet, evidence_manifest_hash, manifest_content_hash))

        # Check 3: Manifest freshness
        checks.append(self._check_manifest_fresh(manifest_expires_at))

        # Check 4: Gate type met (T-02-18)
        manifest_required_gate = _minimum_gate_for_manifest(manifest_risk_tier, manifest_bc)
        effective_required_gate = max(
            required_gate_type,
            manifest_required_gate,
            key=lambda gate: _GATE_STRICTNESS[gate],
        )
        checks.append(
            self._check_gate_type(
                effective_required_gate,
                actual_gate_type,
                manifest_required_gate=manifest_required_gate,
                caller_required_gate=required_gate_type,
            )
        )

        # Check 5: Review complete
        checks.append(self._check_review_complete(review_sub_state, workflow_state))

        # Determine overall result
        failed = [c for c in checks if not c.passed]
        allowed = len(failed) == 0
        reason = ""
        if not allowed:
            reason = ", ".join(c.name for c in failed)

        decision = MergeDecision(allowed=allowed, checks=checks, reason=reason)

        # Log MERGE event to audit ledger (T-02-19: always log)
        if self._audit_ledger is not None:
            await self._audit_ledger.append_event(  # type: ignore[attr-defined]
                event_type=EventType.MERGE,
                actor="control_plane",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=(f"Merge validation for {manifest_id}: {'allowed' if allowed else 'blocked'}"),
                decision="allow" if allowed else "block",
                rationale=reason if reason else "All checks passed",
            )

        return decision

    # ------------------------------------------------------------------
    # Individual check methods (each independently testable)
    # ------------------------------------------------------------------

    def _check_kill_switch(self) -> MergeCheck:
        """Check if kill switch allows merges (T-02-20).

        Returns passed=True if kill_switch is None or not halted.
        Returns passed=False if kill_switch.is_halted("merges") is True.
        """
        if self._kill_switch is None:
            return MergeCheck(
                name="kill_switch_clear",
                passed=True,
                detail="No kill switch configured",
            )

        if self._kill_switch.is_halted("merges"):
            return MergeCheck(
                name="kill_switch_clear",
                passed=False,
                detail="Kill switch is active for merges",
            )

        return MergeCheck(
            name="kill_switch_clear",
            passed=True,
            detail="Kill switch is not active for merges",
        )

    def _check_evidence_exists(
        self,
        evidence_packet: dict | None,
        evidence_manifest_hash: str | None,
        manifest_content_hash: str,
    ) -> MergeCheck:
        """Check that evidence packet exists, is non-empty, and matches manifest.

        Validates both existence and hash integrity (T-02-17).
        """
        if evidence_packet is None:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail="Evidence packet is missing",
            )

        if not evidence_packet:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail="Evidence packet is empty",
            )

        if not manifest_content_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail="Manifest or evidence hash is missing",
            )

        embedded_manifest_hash = extract_evidence_manifest_hash(evidence_packet)
        if not embedded_manifest_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail="Evidence packet is missing embedded manifest hash",
            )

        if evidence_manifest_hash and evidence_manifest_hash != embedded_manifest_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail=(
                    f"Evidence manifest hash mismatch: packet embeds {embedded_manifest_hash}, "
                    f"caller supplied {evidence_manifest_hash}"
                ),
            )

        # Check hash match (T-02-17: reviewed evidence must be for this manifest)
        if embedded_manifest_hash != manifest_content_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail=(
                    f"Evidence manifest hash mismatch: expected {manifest_content_hash}, got {embedded_manifest_hash}"
                ),
            )

        reviewed_evidence_hash = extract_reviewed_evidence_hash(evidence_packet)
        if not reviewed_evidence_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail="Evidence packet is missing reviewed evidence hash",
            )

        actual_reviewed_evidence_hash = compute_reviewed_evidence_hash(evidence_packet)
        if reviewed_evidence_hash != actual_reviewed_evidence_hash:
            return MergeCheck(
                name="evidence_exists",
                passed=False,
                detail=(
                    "Reviewed evidence hash mismatch: "
                    f"expected {reviewed_evidence_hash}, got {actual_reviewed_evidence_hash}"
                ),
            )

        return MergeCheck(
            name="evidence_exists",
            passed=True,
            detail="Evidence packet exists and reviewed evidence matches manifest",
        )

    def _check_manifest_fresh(self, expires_at: datetime) -> MergeCheck:
        """Check that the manifest has not expired."""
        now = datetime.now(timezone.utc)
        if expires_at < now:
            return MergeCheck(
                name="manifest_fresh",
                passed=False,
                detail=f"Manifest expired at {expires_at.isoformat()}",
            )

        return MergeCheck(
            name="manifest_fresh",
            passed=True,
            detail=f"Manifest valid until {expires_at.isoformat()}",
        )

    def _check_gate_type(
        self,
        required_gate_type: GateType,
        actual_gate_type: GateType,
        *,
        manifest_required_gate: GateType | None = None,
        caller_required_gate: GateType | None = None,
    ) -> MergeCheck:
        """Check that actual gate type is at least as restrictive as required."""
        required_level = _GATE_STRICTNESS[required_gate_type]
        actual_level = _GATE_STRICTNESS[actual_gate_type]

        if actual_level < required_level:
            if (
                manifest_required_gate is not None
                and caller_required_gate is not None
                and _GATE_STRICTNESS[manifest_required_gate] > _GATE_STRICTNESS[caller_required_gate]
            ):
                detail = (
                    f"Manifest requires {manifest_required_gate.value} gate, "
                    f"caller requested {caller_required_gate.value}, actual {actual_gate_type.value}"
                )
            else:
                detail = f"Required {required_gate_type.value}, actual {actual_gate_type.value}"
            return MergeCheck(
                name="gate_type_met",
                passed=False,
                detail=detail,
            )

        return MergeCheck(
            name="gate_type_met",
            passed=True,
            detail=f"Required {required_gate_type.value}, actual {actual_gate_type.value}",
        )

    def _check_review_complete(
        self,
        review_sub_state: str,
        workflow_state: str,
    ) -> MergeCheck:
        """Check that review is complete (sub_state=decision, state=approved)."""
        issues: list[str] = []

        if workflow_state != "approved":
            issues.append(f"workflow_state is '{workflow_state}', expected 'approved'")

        if review_sub_state != "decision":
            issues.append(f"review_sub_state is '{review_sub_state}', expected 'decision'")

        if issues:
            return MergeCheck(
                name="review_complete",
                passed=False,
                detail="; ".join(issues),
            )

        return MergeCheck(
            name="review_complete",
            passed=True,
            detail="Review is complete (approved, decision reached)",
        )
