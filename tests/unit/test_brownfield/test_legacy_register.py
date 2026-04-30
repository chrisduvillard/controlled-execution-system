"""Tests for LegacyBehaviorService (BROWN-01, BROWN-02, BROWN-03).

Verifies:
- register_behavior creates and persists ObservedLegacyBehavior
- register_behavior NEVER creates PRLItem (BROWN-02)
- get_pending_behaviors / get_behaviors_by_system filtering
- review_behavior sets disposition and logs to audit ledger
- promote_to_prl creates new PRLItem with back-reference (BROWN-03)
- discard_behavior marks entry as discarded
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ces.brownfield.services.legacy_register import LegacyBehaviorService
from ces.control.models.prl_item import PRLItem
from ces.harness.models.observed_legacy import ObservedLegacyBehavior
from ces.shared.enums import LegacyDisposition


@pytest.fixture
def mock_repository() -> AsyncMock:
    """Create a mock LegacyBehaviorRepository."""
    repo = AsyncMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_system = AsyncMock(return_value=[])
    repo.get_pending = AsyncMock(return_value=[])
    repo.update_disposition = AsyncMock()
    repo.mark_promoted = AsyncMock()
    return repo


@pytest.fixture
def mock_audit_ledger() -> AsyncMock:
    """Create a mock audit ledger."""
    ledger = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


@pytest.fixture
def service(mock_repository: AsyncMock, mock_audit_ledger: AsyncMock) -> LegacyBehaviorService:
    """Create a LegacyBehaviorService with mocked dependencies."""
    return LegacyBehaviorService(
        repository=mock_repository,
        audit_ledger=mock_audit_ledger,
    )


class TestRegisterBehavior:
    """Tests for register_behavior method."""

    @pytest.mark.asyncio
    async def test_creates_observed_legacy_behavior(
        self, service: LegacyBehaviorService, mock_repository: AsyncMock
    ) -> None:
        """Test 1: register_behavior creates ObservedLegacyBehavior and persists to DB."""
        mock_repository.save.return_value = MagicMock()

        result = await service.register_behavior(
            system="legacy-billing",
            behavior_description="Tax calculated before discount",
            inferred_by="agent-001",
            confidence=0.85,
        )

        assert isinstance(result, ObservedLegacyBehavior)
        assert result.system == "legacy-billing"
        assert result.behavior_description == "Tax calculated before discount"
        assert result.inferred_by == "agent-001"
        assert result.confidence == 0.85
        assert result.entry_id.startswith("OLB-")
        assert result.disposition is None
        assert result.discarded is False
        mock_repository.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_to_audit_ledger(
        self, service: LegacyBehaviorService, mock_repository: AsyncMock, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 2: register_behavior logs registration to audit ledger."""
        mock_repository.save.return_value = MagicMock()

        await service.register_behavior(
            system="legacy-billing",
            behavior_description="Tax calculated before discount",
            inferred_by="agent-001",
            confidence=0.85,
        )

        mock_audit_ledger.append_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_never_creates_prl_item(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 3: BROWN-02 invariant: register_behavior never creates a PRLItem directly."""
        mock_repository.save.return_value = MagicMock()

        with patch("ces.brownfield.services.legacy_register.PRLItem") as mock_prl:
            await service.register_behavior(
                system="legacy-billing",
                behavior_description="Tax calculated before discount",
                inferred_by="agent-001",
                confidence=0.85,
            )
            mock_prl.assert_not_called()


class TestGetBehaviors:
    """Tests for get_pending_behaviors and get_behaviors_by_system."""

    @pytest.mark.asyncio
    async def test_get_pending_behaviors(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 4: get_pending_behaviors returns only pending, non-discarded entries."""
        pending_row = MagicMock()
        pending_row.entry_id = "OLB-abc123"
        pending_row.system = "legacy-billing"
        pending_row.behavior_description = "Tax calculated before discount"
        pending_row.inferred_by = "agent-001"
        pending_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        pending_row.confidence = 0.85
        pending_row.disposition = None
        pending_row.reviewed_by = None
        pending_row.reviewed_at = None
        pending_row.promoted_to_prl_id = None
        pending_row.discarded = False

        mock_repository.get_pending.return_value = [pending_row]

        result = await service.get_pending_behaviors()

        assert len(result) == 1
        assert result[0].entry_id == "OLB-abc123"
        assert result[0].disposition is None
        assert result[0].discarded is False

    @pytest.mark.asyncio
    async def test_get_behaviors_by_system(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 5: get_behaviors_by_system filters by system name."""
        row = MagicMock()
        row.entry_id = "OLB-abc123"
        row.system = "legacy-billing"
        row.behavior_description = "Tax calculated before discount"
        row.inferred_by = "agent-001"
        row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row.confidence = 0.85
        row.disposition = None
        row.reviewed_by = None
        row.reviewed_at = None
        row.promoted_to_prl_id = None
        row.discarded = False

        mock_repository.get_by_system.return_value = [row]

        result = await service.get_behaviors_by_system("legacy-billing")

        assert len(result) == 1
        assert result[0].system == "legacy-billing"
        mock_repository.get_by_system.assert_called_once_with("legacy-billing")


class TestReviewBehavior:
    """Tests for review_behavior method."""

    @pytest.mark.asyncio
    async def test_review_sets_disposition(
        self, service: LegacyBehaviorService, mock_repository: AsyncMock, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 9: review_behavior sets disposition and reviewed_by/reviewed_at, logs to audit ledger."""
        existing_row = MagicMock()
        existing_row.entry_id = "OLB-abc123"
        existing_row.system = "legacy-billing"
        existing_row.behavior_description = "Tax calculated before discount"
        existing_row.inferred_by = "agent-001"
        existing_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        existing_row.confidence = 0.85
        existing_row.disposition = None
        existing_row.reviewed_by = None
        existing_row.reviewed_at = None
        existing_row.promoted_to_prl_id = None
        existing_row.discarded = False

        updated_row = MagicMock()
        updated_row.entry_id = "OLB-abc123"
        updated_row.system = "legacy-billing"
        updated_row.behavior_description = "Tax calculated before discount"
        updated_row.inferred_by = "agent-001"
        updated_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        updated_row.confidence = 0.85
        updated_row.disposition = "preserve"
        updated_row.reviewed_by = "human-reviewer"
        updated_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        updated_row.promoted_to_prl_id = None
        updated_row.discarded = False

        mock_repository.get_by_id.return_value = existing_row
        mock_repository.update_disposition.return_value = updated_row

        result = await service.review_behavior(
            entry_id="OLB-abc123",
            disposition=LegacyDisposition.PRESERVE,
            reviewed_by="human-reviewer",
        )

        assert isinstance(result, ObservedLegacyBehavior)
        assert result.disposition == LegacyDisposition.PRESERVE
        assert result.reviewed_by == "human-reviewer"
        mock_audit_ledger.append_event.assert_called_once()


class TestPromoteToPrl:
    """Tests for promote_to_prl method (BROWN-03 copy-on-promote)."""

    @pytest.mark.asyncio
    async def test_creates_prl_item(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 10: promote_to_prl creates a new PRLItem with correct fields."""
        reviewed_row = MagicMock()
        reviewed_row.entry_id = "OLB-abc123"
        reviewed_row.system = "legacy-billing"
        reviewed_row.behavior_description = "Tax calculated before discount"
        reviewed_row.inferred_by = "agent-001"
        reviewed_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False

        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.promoted_to_prl_id = "PRL-placeholder"
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = reviewed_row
        mock_repository.mark_promoted.return_value = promoted_row

        entry, prl_item = await service.promote_to_prl(
            entry_id="OLB-abc123",
            approver="lead-engineer",
        )

        assert isinstance(prl_item, PRLItem)
        assert prl_item.schema_type == "prl_item"
        assert prl_item.statement == "Tax calculated before discount"
        assert prl_item.prl_id.startswith("PRL-")
        mock_repository.save_prl_item.assert_awaited_once_with(prl_item)

    @pytest.mark.asyncio
    async def test_sets_back_reference(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 11: promote_to_prl sets back-reference on register entry."""
        reviewed_row = MagicMock()
        reviewed_row.entry_id = "OLB-abc123"
        reviewed_row.system = "legacy-billing"
        reviewed_row.behavior_description = "Tax calculated before discount"
        reviewed_row.inferred_by = "agent-001"
        reviewed_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False

        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.promoted_to_prl_id = "PRL-xxx"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = reviewed_row
        mock_repository.mark_promoted.return_value = promoted_row

        entry, prl_item = await service.promote_to_prl(
            entry_id="OLB-abc123",
            approver="lead-engineer",
        )

        mock_repository.mark_promoted.assert_called_once()
        call_args = mock_repository.mark_promoted.call_args
        assert call_args[0][0] == "OLB-abc123"  # entry_id
        assert call_args[0][1].startswith("PRL-")  # prl_id

    @pytest.mark.asyncio
    async def test_preserves_register_entry(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 12: promote_to_prl does NOT delete the register entry (copy-on-promote)."""
        reviewed_row = MagicMock()
        reviewed_row.entry_id = "OLB-abc123"
        reviewed_row.system = "legacy-billing"
        reviewed_row.behavior_description = "Tax calculated before discount"
        reviewed_row.inferred_by = "agent-001"
        reviewed_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False

        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.promoted_to_prl_id = "PRL-xxx"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = reviewed_row
        mock_repository.mark_promoted.return_value = promoted_row

        entry, prl_item = await service.promote_to_prl(
            entry_id="OLB-abc123",
            approver="lead-engineer",
        )

        # Verify no delete was called -- copy-on-promote preserves original
        mock_repository.delete = AsyncMock()
        mock_repository.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_approver(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 13: promote_to_prl requires human approver argument."""
        reviewed_row = MagicMock()
        reviewed_row.entry_id = "OLB-abc123"
        reviewed_row.system = "legacy-billing"
        reviewed_row.behavior_description = "Tax calculated before discount"
        reviewed_row.inferred_by = "agent-001"
        reviewed_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False

        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.promoted_to_prl_id = "PRL-xxx"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = reviewed_row
        mock_repository.mark_promoted.return_value = promoted_row

        # Calling with approver succeeds
        entry, prl_item = await service.promote_to_prl(
            entry_id="OLB-abc123",
            approver="lead-engineer",
        )
        assert prl_item.owner == "lead-engineer"

    @pytest.mark.asyncio
    async def test_logs_promotion_to_audit_ledger(
        self, service: LegacyBehaviorService, mock_repository: AsyncMock, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 14: promote_to_prl logs promotion event to audit ledger."""
        reviewed_row = MagicMock()
        reviewed_row.entry_id = "OLB-abc123"
        reviewed_row.system = "legacy-billing"
        reviewed_row.behavior_description = "Tax calculated before discount"
        reviewed_row.inferred_by = "agent-001"
        reviewed_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False

        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.promoted_to_prl_id = "PRL-xxx"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = reviewed_row
        mock_repository.mark_promoted.return_value = promoted_row

        await service.promote_to_prl(
            entry_id="OLB-abc123",
            approver="lead-engineer",
        )

        mock_audit_ledger.append_event.assert_called_once()


class TestDiscardBehavior:
    """Tests for discard_behavior method."""

    @pytest.mark.asyncio
    async def test_marks_as_discarded(
        self, service: LegacyBehaviorService, mock_repository: AsyncMock, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 15: discard_behavior marks entry as discarded=True, logs to audit ledger."""
        existing_row = MagicMock()
        existing_row.entry_id = "OLB-abc123"
        existing_row.system = "legacy-billing"
        existing_row.behavior_description = "Tax calculated before discount"
        existing_row.inferred_by = "agent-001"
        existing_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        existing_row.confidence = 0.85
        existing_row.disposition = None
        existing_row.reviewed_by = None
        existing_row.reviewed_at = None
        existing_row.promoted_to_prl_id = None
        existing_row.discarded = False

        updated_row = MagicMock()
        updated_row.entry_id = "OLB-abc123"
        updated_row.system = "legacy-billing"
        updated_row.behavior_description = "Tax calculated before discount"
        updated_row.inferred_by = "agent-001"
        updated_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        updated_row.confidence = 0.85
        updated_row.disposition = "retire"
        updated_row.reviewed_by = "human-reviewer"
        updated_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        updated_row.promoted_to_prl_id = None
        updated_row.discarded = True

        mock_repository.get_by_id.return_value = existing_row
        mock_repository.update_disposition.return_value = updated_row

        result = await service.discard_behavior(
            entry_id="OLB-abc123",
            reviewed_by="human-reviewer",
            reason="Not a real behavior",
        )

        assert isinstance(result, ObservedLegacyBehavior)
        assert result.discarded is True
        mock_audit_ledger.append_event.assert_called()

    @pytest.mark.asyncio
    async def test_discard_on_promoted_raises(self, service: LegacyBehaviorService, mock_repository: AsyncMock) -> None:
        """Test 16: discard_behavior on already-promoted entry raises ValueError."""
        promoted_row = MagicMock()
        promoted_row.entry_id = "OLB-abc123"
        promoted_row.system = "legacy-billing"
        promoted_row.behavior_description = "Tax calculated before discount"
        promoted_row.inferred_by = "agent-001"
        promoted_row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        promoted_row.promoted_to_prl_id = "PRL-xyz"
        promoted_row.discarded = False

        mock_repository.get_by_id.return_value = promoted_row

        with pytest.raises(ValueError, match="promoted"):
            await service.discard_behavior(
                entry_id="OLB-abc123",
                reviewed_by="human-reviewer",
                reason="Wrong behavior",
            )


class TestLegacyRegisterErrorPaths:
    """Tests for error paths to improve coverage."""

    @pytest.mark.asyncio
    async def test_register_without_repository(self) -> None:
        """register_behavior works without repository (in-memory only)."""
        svc = LegacyBehaviorService(repository=None, audit_ledger=None)
        result = await svc.register_behavior(
            system="legacy",
            behavior_description="Test behavior",
            inferred_by="agent-001",
            confidence=0.5,
        )
        assert result.entry_id.startswith("OLB-")
        assert result.system == "legacy"

    @pytest.mark.asyncio
    async def test_register_without_audit_ledger(self, mock_repository: AsyncMock) -> None:
        """register_behavior works without audit ledger."""
        mock_repository.save.return_value = MagicMock()
        svc = LegacyBehaviorService(repository=mock_repository, audit_ledger=None)
        result = await svc.register_behavior(
            system="legacy",
            behavior_description="Test",
            inferred_by="agent-001",
            confidence=0.7,
        )
        assert result.entry_id.startswith("OLB-")

    @pytest.mark.asyncio
    async def test_get_pending_without_repository(self) -> None:
        """get_pending_behaviors returns empty list without repository."""
        svc = LegacyBehaviorService(repository=None)
        result = await svc.get_pending_behaviors()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_system_without_repository(self) -> None:
        """get_behaviors_by_system returns empty list without repository."""
        svc = LegacyBehaviorService(repository=None)
        result = await svc.get_behaviors_by_system("legacy")
        assert result == []

    @pytest.mark.asyncio
    async def test_review_without_repository_raises(self) -> None:
        """review_behavior raises RuntimeError without repository."""
        svc = LegacyBehaviorService(repository=None)
        with pytest.raises(RuntimeError, match="Repository required"):
            await svc.review_behavior(
                entry_id="OLB-abc",
                disposition=LegacyDisposition.PRESERVE,
                reviewed_by="user",
            )

    @pytest.mark.asyncio
    async def test_review_not_found_raises(self, mock_repository: AsyncMock) -> None:
        """review_behavior raises ValueError if entry not found."""
        mock_repository.get_by_id.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="not found"):
            await svc.review_behavior(
                entry_id="OLB-nonexistent",
                disposition=LegacyDisposition.PRESERVE,
                reviewed_by="user",
            )

    @pytest.mark.asyncio
    async def test_review_already_disposed_raises(self, mock_repository: AsyncMock) -> None:
        """review_behavior raises ValueError if already has disposition."""
        row = MagicMock()
        row.disposition = "preserve"
        mock_repository.get_by_id.return_value = row
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="already has disposition"):
            await svc.review_behavior(
                entry_id="OLB-abc",
                disposition=LegacyDisposition.CHANGE,
                reviewed_by="user",
            )

    @pytest.mark.asyncio
    async def test_review_update_fails_raises(self, mock_repository: AsyncMock) -> None:
        """review_behavior raises ValueError if update_disposition returns None."""
        row = MagicMock()
        row.disposition = None
        mock_repository.get_by_id.return_value = row
        mock_repository.update_disposition.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="Failed to update"):
            await svc.review_behavior(
                entry_id="OLB-abc",
                disposition=LegacyDisposition.PRESERVE,
                reviewed_by="user",
            )

    @pytest.mark.asyncio
    async def test_promote_without_repository_raises(self) -> None:
        """promote_to_prl raises RuntimeError without repository."""
        svc = LegacyBehaviorService(repository=None)
        with pytest.raises(RuntimeError, match="Repository required"):
            await svc.promote_to_prl(entry_id="OLB-abc", approver="user")

    @pytest.mark.asyncio
    async def test_promote_not_found_raises(self, mock_repository: AsyncMock) -> None:
        """promote_to_prl raises ValueError if entry not found."""
        mock_repository.get_by_id.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="not found"):
            await svc.promote_to_prl(entry_id="OLB-nonexistent", approver="user")

    @pytest.mark.asyncio
    async def test_promote_not_reviewed_raises(self, mock_repository: AsyncMock) -> None:
        """promote_to_prl raises ValueError if not yet reviewed."""
        row = MagicMock()
        row.disposition = None
        row.discarded = False
        row.promoted_to_prl_id = None
        mock_repository.get_by_id.return_value = row
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="must be reviewed"):
            await svc.promote_to_prl(entry_id="OLB-abc", approver="user")

    @pytest.mark.asyncio
    async def test_promote_discarded_raises(self, mock_repository: AsyncMock) -> None:
        """promote_to_prl raises ValueError if entry is discarded."""
        row = MagicMock()
        row.disposition = "retire"
        row.discarded = True
        row.promoted_to_prl_id = None
        mock_repository.get_by_id.return_value = row
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="discarded"):
            await svc.promote_to_prl(entry_id="OLB-abc", approver="user")

    @pytest.mark.asyncio
    async def test_promote_already_promoted_raises(self, mock_repository: AsyncMock) -> None:
        """promote_to_prl raises ValueError if already promoted."""
        row = MagicMock()
        row.disposition = "preserve"
        row.discarded = False
        row.promoted_to_prl_id = "PRL-existing"
        mock_repository.get_by_id.return_value = row
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="already promoted"):
            await svc.promote_to_prl(entry_id="OLB-abc", approver="user")

    @pytest.mark.asyncio
    async def test_promote_mark_fails_raises(self, mock_repository: AsyncMock) -> None:
        """promote_to_prl raises ValueError if mark_promoted returns None."""
        row = MagicMock()
        row.entry_id = "OLB-abc"
        row.system = "legacy"
        row.behavior_description = "Test"
        row.inferred_by = "agent"
        row.inferred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row.confidence = 0.8
        row.disposition = "preserve"
        row.discarded = False
        row.promoted_to_prl_id = None
        mock_repository.get_by_id.return_value = row
        mock_repository.mark_promoted.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="Failed to mark"):
            await svc.promote_to_prl(entry_id="OLB-abc", approver="user")

    @pytest.mark.asyncio
    async def test_discard_without_repository_raises(self) -> None:
        """discard_behavior raises RuntimeError without repository."""
        svc = LegacyBehaviorService(repository=None)
        with pytest.raises(RuntimeError, match="Repository required"):
            await svc.discard_behavior(
                entry_id="OLB-abc",
                reviewed_by="user",
                reason="test",
            )

    @pytest.mark.asyncio
    async def test_discard_not_found_raises(self, mock_repository: AsyncMock) -> None:
        """discard_behavior raises ValueError if entry not found."""
        mock_repository.get_by_id.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="not found"):
            await svc.discard_behavior(
                entry_id="OLB-nonexistent",
                reviewed_by="user",
                reason="test",
            )

    @pytest.mark.asyncio
    async def test_discard_update_fails_raises(self, mock_repository: AsyncMock) -> None:
        """discard_behavior raises ValueError if update_disposition returns None."""
        row = MagicMock()
        row.promoted_to_prl_id = None
        mock_repository.get_by_id.return_value = row
        mock_repository.update_disposition.return_value = None
        svc = LegacyBehaviorService(repository=mock_repository)
        with pytest.raises(ValueError, match="Failed to update"):
            await svc.discard_behavior(
                entry_id="OLB-abc",
                reviewed_by="user",
                reason="test",
            )
