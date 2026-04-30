"""Audit ledger compatibility tests with real PostgreSQL.

Tests the full audit ledger lifecycle with testcontainers:
- Hash chain integrity across multiple entries
- Query by event type, actor
- DB trigger enforcement (UPDATE/DELETE blocked)
- Mixed event types

These tests cover retained repository compatibility code, not the supported
local builder-first CES workflow.

Requires Docker to be running. All tests are marked @pytest.mark.integration.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ces.control.services.audit_ledger import AuditLedgerService
from ces.shared.enums import ActorType, EventType, InvalidationSeverity
from tests.integration._compat.control_db.repository import AuditRepository

# Test secret key (32 bytes for HMAC-SHA256)
TEST_SECRET_KEY = b"integration-test-key-32bytes!!"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_chain_integrity(async_session: AsyncSession) -> None:
    """Append several entries and verify the HMAC chain."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)
    project_id = "proj-audit-chain-integrity"

    # Append a chain of entries
    e1 = await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Created vision anchor",
        project_id=project_id,
    )
    e2 = await service.record_state_transition(
        "M-001", "system", ActorType.CONTROL_PLANE, "queued", "in_flight", project_id=project_id
    )
    e3 = await service.record_approval("M-001", "reviewer", "approve", "Looks good", project_id=project_id)
    e4 = await service.record_invalidation(
        "art-001", ["M-001"], InvalidationSeverity.HIGH, "Source changed", project_id=project_id
    )
    e5 = await service.record_classification(
        "M-002", "classifier", ActorType.AGENT, "Tier B, BC2, Class 3", project_id=project_id
    )

    await async_session.commit()

    # Verify chain integrity
    assert await service.verify_integrity(project_id=project_id)

    # Verify chain linkage
    assert e1.prev_hash == "GENESIS"
    assert e2.prev_hash == e1.entry_hash
    assert e3.prev_hash == e2.entry_hash
    assert e4.prev_hash == e3.entry_hash
    assert e5.prev_hash == e4.entry_hash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_by_event_type(async_session: AsyncSession) -> None:
    """Query by event type returns correct subset."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)

    # Append mixed event types
    await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Truth change 1",
    )
    await service.record_approval("M-001", "reviewer", "approve", "LGTM")
    await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Truth change 2",
    )

    await async_session.commit()

    # Query for TRUTH_CHANGE entries only
    truth_entries = await service.query_by_event_type(EventType.TRUTH_CHANGE)
    assert len(truth_entries) >= 2
    assert all(e.event_type == EventType.TRUTH_CHANGE for e in truth_entries)

    # Query for APPROVAL entries
    approval_entries = await service.query_by_event_type(EventType.APPROVAL)
    assert len(approval_entries) >= 1
    assert all(e.event_type == EventType.APPROVAL for e in approval_entries)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_by_actor(async_session: AsyncSession) -> None:
    """Query by actor returns correct subset."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)

    await service.append_event(
        EventType.TRUTH_CHANGE,
        "alice",
        ActorType.HUMAN,
        "Alice's change",
    )
    await service.append_event(
        EventType.CLASSIFICATION,
        "bob",
        ActorType.AGENT,
        "Bob's classification",
    )
    await service.append_event(
        EventType.APPROVAL,
        "alice",
        ActorType.HUMAN,
        "Alice's approval",
    )

    await async_session.commit()

    alice_entries = await service.query_by_actor("alice")
    assert len(alice_entries) >= 2
    assert all(e.actor == "alice" for e in alice_entries)

    bob_entries = await service.query_by_actor("bob")
    assert len(bob_entries) >= 1
    assert all(e.actor == "bob" for e in bob_entries)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_trigger_blocks_update(
    async_session: AsyncSession,
    sync_engine,
) -> None:
    """DB trigger must reject UPDATE on audit entries."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)

    entry = await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Entry to attempt update on",
    )
    await async_session.commit()

    # Attempt UPDATE via raw SQL -- should be rejected by trigger
    with pytest.raises(Exception), sync_engine.connect() as conn:
        conn.execute(
            text("UPDATE control.audit_entries SET action_summary = 'tampered' WHERE entry_id = :eid"),
            {"eid": entry.entry_id},
        )
        conn.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_trigger_blocks_delete(
    async_session: AsyncSession,
    sync_engine,
) -> None:
    """DB trigger must reject DELETE on audit entries."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)

    entry = await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Entry to attempt delete on",
    )
    await async_session.commit()

    # Attempt DELETE via raw SQL -- should be rejected by trigger
    with pytest.raises(Exception), sync_engine.connect() as conn:
        conn.execute(
            text("DELETE FROM control.audit_entries WHERE entry_id = :eid"),
            {"eid": entry.entry_id},
        )
        conn.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mixed_event_types_chain_integrity(
    async_session: AsyncSession,
) -> None:
    """Verify chain integrity after appending mixed event types."""
    repo = AuditRepository(async_session)
    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=repo)
    project_id = "proj-audit-chain-mixed"

    # Append a variety of event types
    await service.append_event(
        EventType.TRUTH_CHANGE,
        "admin",
        ActorType.HUMAN,
        "Vision anchor created",
        project_id=project_id,
    )
    await service.record_state_transition(
        "M-001", "control_plane", ActorType.CONTROL_PLANE, "queued", "in_flight", project_id=project_id
    )
    await service.record_approval("M-001", "reviewer", "approve", "Ship it", project_id=project_id)
    await service.record_invalidation(
        "art-001", ["M-001", "M-002"], InvalidationSeverity.MEDIUM, "Source drift", project_id=project_id
    )
    await service.record_truth_change("art-002", "admin", ActorType.HUMAN, "Updated PRL", project_id=project_id)
    await service.record_classification(
        "M-003", "oracle", ActorType.AGENT, "Tier A, BC3, Class 5", project_id=project_id
    )
    await service.append_event(
        EventType.KILL_SWITCH,
        "control_plane",
        ActorType.CONTROL_PLANE,
        "Emergency halt triggered",
        project_id=project_id,
    )

    await async_session.commit()

    # Full chain must verify
    assert await service.verify_integrity(project_id=project_id)
