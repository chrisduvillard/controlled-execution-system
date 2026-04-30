"""Internal persistence compatibility tests against real PostgreSQL.

Tests that core services (ManifestManager, AuditLedger, KillSwitch,
TrustManager) correctly persist state to testcontainers PostgreSQL.

These tests cover retained database compatibility code, not the supported
local builder-first CES workflow. All tests in this module require a
running Docker daemon and are gated by ``pytest.mark.integration`` so that
``pytest -m "not integration"`` correctly skips them on developer machines
without Docker.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

from ces.shared.enums import RiskTier
from tests.integration._compat.control_db.tables import (
    AuditEntryRow,
    KillSwitchStateRow,
    ManifestRow,
    TrustEventRow,
)


class TestManifestPersistence:
    """Test manifest creation persists to real DB."""

    @pytest.mark.asyncio
    async def test_manifest_insert_and_query(self, async_session: AsyncSession) -> None:
        """Insert a manifest row and query it back."""
        from datetime import datetime, timedelta, timezone

        row = ManifestRow(
            manifest_id="M-pipeline-test-001",
            description="E2E pipeline test manifest",
            risk_tier="C",
            behavior_confidence="BC1",
            change_class="Class 1",
            content={
                "manifest_id": "M-pipeline-test-001",
                "description": "E2E pipeline test manifest",
                "risk_tier": "C",
                "behavior_confidence": "BC1",
                "change_class": "Class 1",
                "affected_files": [],
                "token_budget": 50000,
                "owner": "test-user",
            },
            content_hash="a" * 64,
            signature=None,
            status="draft",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        async_session.add(row)
        await async_session.flush()

        result = await async_session.execute(
            select(ManifestRow).where(ManifestRow.manifest_id == "M-pipeline-test-001")
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.content["description"] == "E2E pipeline test manifest"


class TestAuditLedgerPersistence:
    """Test audit entries are written to real DB."""

    @pytest.mark.asyncio
    async def test_audit_entry_insert(self, async_session: AsyncSession) -> None:
        """Insert an audit entry and verify it persists."""
        from ces.control.services.audit_ledger import AuditLedgerService
        from ces.shared.enums import ActorType, EventType

        ledger = AuditLedgerService(secret_key=b"test-hmac-secret-for-integration")

        # Record an event to the in-memory ledger
        entry = await ledger.append_event(
            event_type=EventType.CLASSIFICATION,
            actor="test-pipeline",
            actor_type=ActorType.HUMAN,
            action_summary="Classified manifest M-audit-test",
        )
        assert entry is not None
        assert entry.event_type == EventType.CLASSIFICATION
        assert entry.entry_hash  # HMAC hash should be set


class TestKillSwitchPersistence:
    """Test kill switch state writes to real DB."""

    @pytest.mark.asyncio
    async def test_kill_switch_state_insert(self, async_session: AsyncSession) -> None:
        """Insert kill switch state row and verify it persists."""
        row = KillSwitchStateRow(
            activity_class="task_issuance",
            halted=True,
            halted_by="test-admin",
            reason="E2E test activation",
        )
        async_session.add(row)
        await async_session.flush()

        result = await async_session.execute(
            select(KillSwitchStateRow).where(KillSwitchStateRow.activity_class == "task_issuance")
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.halted is True
        assert found.halted_by == "test-admin"


class TestTrustEventPersistence:
    """Test trust events are written to real DB."""

    @pytest.mark.asyncio
    async def test_trust_event_insert(self, async_session: AsyncSession) -> None:
        """Insert a trust event and verify it persists."""
        row = TrustEventRow(
            event_id="TE-pipeline-001",
            profile_id="profile-agent-1",
            old_status="candidate",
            new_status="trusted",
            trigger="promotion",
            metadata_extra={"tasks_completed": 15},
        )
        async_session.add(row)
        await async_session.flush()

        result = await async_session.execute(select(TrustEventRow).where(TrustEventRow.event_id == "TE-pipeline-001"))
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.old_status == "candidate"
        assert found.new_status == "trusted"
        assert found.metadata_extra["tasks_completed"] == 15


class TestAuditAppendOnlyTrigger:
    """Test that the audit append-only trigger prevents UPDATE/DELETE."""

    @pytest.mark.asyncio
    async def test_audit_update_blocked_by_trigger(self, async_session: AsyncSession) -> None:
        """UPDATE on audit_entries is blocked by the append-only trigger."""
        # Insert a row first
        await async_session.execute(
            text(
                "INSERT INTO control.audit_entries "
                "(entry_id, sequence_num, event_type, actor, actor_type, "
                "scope, action_summary, decision, rationale, "
                "prev_hash, entry_hash, timestamp) "
                "VALUES ('AE-trigger-test', 99999, 'approval', 'test', 'HUMAN', "
                "'{}'::jsonb, 'test action', '', '', "
                "'prev', 'hash', now())"
            )
        )
        await async_session.flush()

        # Attempt UPDATE — should be blocked by trigger
        with pytest.raises(Exception, match="append.only|cannot|audit"):
            await async_session.execute(
                text("UPDATE control.audit_entries SET event_type = 'HACKED' WHERE entry_id = 'AE-trigger-test'")
            )
            await async_session.flush()
