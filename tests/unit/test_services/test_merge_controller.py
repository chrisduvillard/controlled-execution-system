"""Unit tests for MergeDecision model and MergeController service.

Tests cover:
- MergeCheck and MergeDecision frozen dataclass behavior
- MergeController.validate_merge with valid conditions (all checks pass)
- Block on missing evidence packet
- Block on expired manifest
- Block on wrong gate type (gate type downgrade)
- Block on incomplete review (sub_state or workflow_state)
- Block on evidence hash mismatch
- Returns ALL failed checks (not short-circuit)
- Kill switch halts merges
- Works without kill switch (None)
- Logs MERGE event to audit ledger
- Exactly 5 named checks in defined order

All tests run in-memory (no database).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.control.models.merge_decision import MergeCheck, MergeDecision
from ces.control.services.merge_controller import MERGE_CHECKS, MergeController
from ces.shared.enums import (
    EventType,
    GateType,
    ReviewSubState,
    WorkflowState,
)

# ---------------------------------------------------------------------------
# Helpers to build test data
# ---------------------------------------------------------------------------


def _valid_merge_kwargs() -> dict:
    """Return a dict of kwargs that produce a passing merge validation."""
    now = datetime.now(timezone.utc)
    return {
        "manifest_id": "M-test-001",
        "manifest_expires_at": now + timedelta(hours=24),
        "manifest_content_hash": "sha256:abc123",
        "manifest_risk_tier": "C",
        "manifest_bc": "BC1",
        "evidence_packet": {"result": "pass", "coverage": 95},
        "evidence_manifest_hash": "sha256:abc123",
        "required_gate_type": GateType.AGENT,
        "actual_gate_type": GateType.AGENT,
        "review_sub_state": ReviewSubState.DECISION.value,
        "workflow_state": WorkflowState.APPROVED.value,
    }


def _mock_kill_switch(halted: bool = False) -> MagicMock:
    """Create a mock kill switch that returns halted for 'merges'."""
    ks = MagicMock()
    ks.is_halted = MagicMock(return_value=halted)
    return ks


def _mock_audit_ledger() -> AsyncMock:
    """Create a mock audit ledger with async append_event."""
    ledger = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


# ---------------------------------------------------------------------------
# MergeCheck and MergeDecision model tests
# ---------------------------------------------------------------------------


class TestMergeDecisionModel:
    """Tests for MergeCheck and MergeDecision frozen dataclasses."""

    def test_merge_check_is_frozen(self):
        """MergeCheck must be a frozen dataclass."""
        check = MergeCheck(name="test", passed=True, detail="ok")
        with pytest.raises(AttributeError):
            check.name = "changed"  # type: ignore[misc]

    def test_merge_decision_is_frozen(self):
        """MergeDecision must be a frozen dataclass."""
        decision = MergeDecision(allowed=True, checks=(), reason="")
        with pytest.raises(AttributeError):
            decision.allowed = False  # type: ignore[misc]

    def test_merge_check_fields(self):
        """MergeCheck has name, passed, detail fields."""
        check = MergeCheck(name="evidence_exists", passed=False, detail="missing")
        assert check.name == "evidence_exists"
        assert check.passed is False
        assert check.detail == "missing"

    def test_merge_decision_fields(self):
        """MergeDecision has allowed, checks, reason fields."""
        checks = (
            MergeCheck(name="a", passed=True, detail="ok"),
            MergeCheck(name="b", passed=False, detail="fail"),
        )
        decision = MergeDecision(allowed=False, checks=checks, reason="b failed")
        assert decision.allowed is False
        assert len(decision.checks) == 2
        assert decision.reason == "b failed"

    def test_merge_decision_defaults(self):
        """MergeDecision defaults to empty checks and empty reason."""
        decision = MergeDecision(allowed=True)
        assert decision.checks == ()
        assert decision.reason == ""


# ---------------------------------------------------------------------------
# MergeController.validate_merge tests
# ---------------------------------------------------------------------------


class TestMergeControllerValidMerge:
    """Tests for validate_merge with valid inputs (all checks pass)."""

    @pytest.mark.asyncio
    async def test_valid_merge_allowed(self):
        """validate_merge with all valid inputs returns allowed=True."""
        controller = MergeController()
        result = await controller.validate_merge(**_valid_merge_kwargs())
        assert result.allowed is True
        assert all(c.passed for c in result.checks)
        assert result.reason == ""

    @pytest.mark.asyncio
    async def test_exactly_five_checks_in_order(self):
        """validate_merge returns exactly 5 checks in the defined order."""
        controller = MergeController()
        result = await controller.validate_merge(**_valid_merge_kwargs())
        check_names = [c.name for c in result.checks]
        assert check_names == MERGE_CHECKS
        assert len(check_names) == 5


class TestMergeControllerBlockNoEvidence:
    """Tests for blocking on missing evidence."""

    @pytest.mark.asyncio
    async def test_block_no_evidence(self):
        """validate_merge with None evidence_packet returns allowed=False."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["evidence_packet"] = None
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        evidence_check = next(c for c in result.checks if c.name == "evidence_exists")
        assert evidence_check.passed is False

    @pytest.mark.asyncio
    async def test_block_empty_evidence(self):
        """validate_merge with empty evidence_packet returns allowed=False."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["evidence_packet"] = {}
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        evidence_check = next(c for c in result.checks if c.name == "evidence_exists")
        assert evidence_check.passed is False

    @pytest.mark.asyncio
    async def test_block_missing_manifest_hash(self):
        """validate_merge blocks when the manifest/evidence hash link is missing."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["manifest_content_hash"] = ""
        kwargs["evidence_manifest_hash"] = ""
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        evidence_check = next(c for c in result.checks if c.name == "evidence_exists")
        assert evidence_check.passed is False
        assert "hash is missing" in evidence_check.detail


class TestMergeControllerFreshness:
    """Tests for manifest freshness check."""

    @pytest.mark.asyncio
    async def test_freshness_expired(self):
        """validate_merge with expired manifest returns allowed=False."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["manifest_expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        fresh_check = next(c for c in result.checks if c.name == "manifest_fresh")
        assert fresh_check.passed is False
        assert "expired" in fresh_check.detail.lower()


class TestMergeControllerGateEnforcement:
    """Tests for gate type enforcement."""

    @pytest.mark.asyncio
    async def test_gate_enforcement_human_required_agent_actual(self):
        """Required HUMAN but actual AGENT -> gate_type_met fails."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["required_gate_type"] = GateType.HUMAN
        kwargs["actual_gate_type"] = GateType.AGENT
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is False

    @pytest.mark.asyncio
    async def test_gate_enforcement_hybrid_required_agent_actual(self):
        """Required HYBRID but actual AGENT -> gate_type_met fails."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["required_gate_type"] = GateType.HYBRID
        kwargs["actual_gate_type"] = GateType.AGENT
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is False

    @pytest.mark.asyncio
    async def test_manifest_tier_a_cannot_be_downgraded_by_caller(self):
        """Tier A manifests require HUMAN even if the caller passes AGENT."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["manifest_risk_tier"] = "A"
        kwargs["required_gate_type"] = GateType.AGENT
        kwargs["actual_gate_type"] = GateType.AGENT

        result = await controller.validate_merge(**kwargs)

        assert result.allowed is False
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is False
        assert "manifest requires human" in gate_check.detail.lower()

    @pytest.mark.asyncio
    async def test_manifest_bc3_cannot_be_downgraded_by_caller(self):
        """BC3 manifests require HUMAN even if the caller passes AGENT."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["manifest_risk_tier"] = "C"
        kwargs["manifest_bc"] = "BC3"
        kwargs["required_gate_type"] = GateType.AGENT
        kwargs["actual_gate_type"] = GateType.AGENT

        result = await controller.validate_merge(**kwargs)

        assert result.allowed is False
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is False
        assert "manifest requires human" in gate_check.detail.lower()

    @pytest.mark.asyncio
    async def test_gate_enforcement_human_required_human_actual(self):
        """Required HUMAN and actual HUMAN -> gate_type_met passes."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["required_gate_type"] = GateType.HUMAN
        kwargs["actual_gate_type"] = GateType.HUMAN
        result = await controller.validate_merge(**kwargs)
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is True

    @pytest.mark.asyncio
    async def test_gate_enforcement_agent_required_human_actual(self):
        """Required AGENT but actual HUMAN -> passes (more restrictive OK)."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["required_gate_type"] = GateType.AGENT
        kwargs["actual_gate_type"] = GateType.HUMAN
        result = await controller.validate_merge(**kwargs)
        gate_check = next(c for c in result.checks if c.name == "gate_type_met")
        assert gate_check.passed is True


class TestMergeControllerReviewComplete:
    """Tests for review completeness check."""

    @pytest.mark.asyncio
    async def test_incomplete_review_sub_state(self):
        """review_sub_state not 'decision' -> review_complete fails."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["review_sub_state"] = ReviewSubState.TRIAGE.value
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        review_check = next(c for c in result.checks if c.name == "review_complete")
        assert review_check.passed is False

    @pytest.mark.asyncio
    async def test_wrong_workflow_state(self):
        """workflow_state not 'approved' -> review_complete fails."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["workflow_state"] = WorkflowState.UNDER_REVIEW.value
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        review_check = next(c for c in result.checks if c.name == "review_complete")
        assert review_check.passed is False


class TestMergeControllerEvidenceHashMismatch:
    """Tests for evidence/manifest hash mismatch."""

    @pytest.mark.asyncio
    async def test_evidence_hash_mismatch(self):
        """evidence_manifest_hash != manifest_content_hash -> fails."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        kwargs["evidence_manifest_hash"] = "sha256:DIFFERENT"
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        evidence_check = next(c for c in result.checks if c.name == "evidence_exists")
        assert evidence_check.passed is False


class TestMergeControllerMultipleFailures:
    """Tests for returning ALL failed checks, not just the first."""

    @pytest.mark.asyncio
    async def test_returns_all_failed_checks(self):
        """validate_merge returns ALL failed checks, not just first."""
        controller = MergeController()
        kwargs = _valid_merge_kwargs()
        # Invalidate multiple checks at once
        kwargs["evidence_packet"] = None
        kwargs["manifest_expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)
        kwargs["review_sub_state"] = ReviewSubState.TRIAGE.value
        result = await controller.validate_merge(**kwargs)
        assert result.allowed is False
        failed = [c for c in result.checks if not c.passed]
        # Should have at least 3 failures: evidence_exists, manifest_fresh, review_complete
        assert len(failed) >= 3
        failed_names = {c.name for c in failed}
        assert "evidence_exists" in failed_names
        assert "manifest_fresh" in failed_names
        assert "review_complete" in failed_names


class TestMergeControllerKillSwitch:
    """Tests for kill switch integration."""

    @pytest.mark.asyncio
    async def test_kill_switch_halted_blocks_merge(self):
        """kill_switch.is_halted('merges') returns True -> allowed=False."""
        ks = _mock_kill_switch(halted=True)
        controller = MergeController(kill_switch=ks)
        result = await controller.validate_merge(**_valid_merge_kwargs())
        assert result.allowed is False
        ks_check = next(c for c in result.checks if c.name == "kill_switch_clear")
        assert ks_check.passed is False
        assert "kill switch" in ks_check.detail.lower()

    @pytest.mark.asyncio
    async def test_kill_switch_not_halted_allows_merge(self):
        """kill_switch.is_halted('merges') returns False -> check passes."""
        ks = _mock_kill_switch(halted=False)
        controller = MergeController(kill_switch=ks)
        result = await controller.validate_merge(**_valid_merge_kwargs())
        ks_check = next(c for c in result.checks if c.name == "kill_switch_clear")
        assert ks_check.passed is True

    @pytest.mark.asyncio
    async def test_no_kill_switch_proceeds_normally(self):
        """Without kill_switch (None) -> kill_switch_clear passes."""
        controller = MergeController(kill_switch=None)
        result = await controller.validate_merge(**_valid_merge_kwargs())
        assert result.allowed is True
        ks_check = next(c for c in result.checks if c.name == "kill_switch_clear")
        assert ks_check.passed is True


class TestMergeControllerAuditLogging:
    """Tests for audit ledger integration."""

    @pytest.mark.asyncio
    async def test_logs_merge_event_to_audit_ledger(self):
        """validate_merge logs a MERGE event to the audit ledger."""
        ledger = _mock_audit_ledger()
        controller = MergeController(audit_ledger=ledger)
        await controller.validate_merge(**_valid_merge_kwargs())
        ledger.append_event.assert_awaited_once()
        call_kwargs = ledger.append_event.call_args
        assert call_kwargs[1]["event_type"] == EventType.MERGE or (
            len(call_kwargs[0]) > 0 and call_kwargs[0][0] == EventType.MERGE
        )

    @pytest.mark.asyncio
    async def test_logs_merge_event_on_failure_too(self):
        """validate_merge logs a MERGE event even when merge is blocked."""
        ledger = _mock_audit_ledger()
        controller = MergeController(audit_ledger=ledger)
        kwargs = _valid_merge_kwargs()
        kwargs["evidence_packet"] = None
        await controller.validate_merge(**kwargs)
        ledger.append_event.assert_awaited_once()
