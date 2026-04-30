"""Unit tests for AuditLedgerService.

Tests the append-only audit ledger with HMAC-SHA256 hash chain integrity.
All tests run in-memory (repository=None) for unit isolation.
"""

from __future__ import annotations

import pytest

from ces.control.models.audit_entry import AuditEntry, AuditScope, CostImpact
from ces.shared.enums import ActorType, EventType, InvalidationSeverity

# Test secret key (32 bytes for HMAC-SHA256)
TEST_SECRET_KEY = b"test-secret-key-32bytes-long!!!!"


@pytest.fixture()
def ledger():
    """Create an in-memory AuditLedgerService with no repository."""
    from ces.control.services.audit_ledger import AuditLedgerService

    return AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=None)


# ---------------------------------------------------------------------------
# Basic append_event tests
# ---------------------------------------------------------------------------


async def test_append_event_creates_entry_with_correct_fields(ledger):
    """append_event creates AuditEntry with correct entry_id, timestamp, event_type, actor fields."""
    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Created vision anchor",
        decision="create",
        rationale="Initial setup",
    )

    assert isinstance(entry, AuditEntry)
    assert entry.entry_id.startswith("AE-")
    assert len(entry.entry_id) == 15  # "AE-" + 12 hex chars
    assert entry.event_type == EventType.TRUTH_CHANGE
    assert entry.actor == "admin"
    assert entry.actor_type == ActorType.HUMAN
    assert entry.action_summary == "Created vision anchor"
    assert entry.decision == "create"
    assert entry.rationale == "Initial setup"
    assert entry.timestamp is not None


async def test_append_event_sets_scope(ledger):
    """append_event correctly sets the scope fields."""
    scope = AuditScope(
        affected_artifacts=("art-1",),
        affected_tasks=("task-1",),
        affected_manifests=("M-001",),
    )
    entry = await ledger.append_event(
        event_type=EventType.APPROVAL,
        actor="reviewer",
        actor_type=ActorType.HUMAN,
        action_summary="Approved manifest",
        scope=scope,
    )

    assert entry.scope.affected_artifacts == ("art-1",)
    assert entry.scope.affected_tasks == ("task-1",)
    assert entry.scope.affected_manifests == ("M-001",)


# ---------------------------------------------------------------------------
# HMAC hash chain tests
# ---------------------------------------------------------------------------


async def test_first_entry_has_genesis_prev_hash(ledger):
    """First entry in chain has prev_hash='GENESIS'."""
    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="First entry",
    )

    assert entry.prev_hash == "GENESIS"
    assert entry.entry_hash is not None
    assert len(entry.entry_hash) == 64  # HMAC-SHA256 hex


async def test_second_entry_links_to_first(ledger):
    """Second entry's prev_hash equals first entry's entry_hash."""
    e1 = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="First",
    )
    e2 = await ledger.append_event(
        event_type=EventType.CLASSIFICATION,
        actor="system",
        actor_type=ActorType.CONTROL_PLANE,
        action_summary="Second",
    )

    assert e2.prev_hash == e1.entry_hash
    assert e2.entry_hash != e1.entry_hash


async def test_hash_chain_three_entries(ledger):
    """Three entries form a valid chain: GENESIS -> e1 -> e2 -> e3."""
    e1 = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Entry 1",
    )
    e2 = await ledger.append_event(
        event_type=EventType.CLASSIFICATION,
        actor="system",
        actor_type=ActorType.CONTROL_PLANE,
        action_summary="Entry 2",
    )
    e3 = await ledger.append_event(
        event_type=EventType.APPROVAL,
        actor="reviewer",
        actor_type=ActorType.HUMAN,
        action_summary="Entry 3",
    )

    assert e1.prev_hash == "GENESIS"
    assert e2.prev_hash == e1.entry_hash
    assert e3.prev_hash == e2.entry_hash


async def test_entry_hash_is_hmac_sha256(ledger):
    """entry_hash is computed as HMAC-SHA256 of entry data + prev_hash."""
    from ces.shared.crypto import compute_entry_hash

    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Test HMAC",
    )

    # Recompute the expected hash
    entry_data = entry.model_dump(mode="json", exclude={"entry_hash"})
    expected = compute_entry_hash(entry_data, entry.prev_hash, TEST_SECRET_KEY)
    assert entry.entry_hash == expected


# ---------------------------------------------------------------------------
# verify_integrity tests
# ---------------------------------------------------------------------------


async def test_verify_integrity_valid_chain(ledger):
    """verify_integrity returns True for a valid chain of 3+ entries."""
    entries = []
    for i in range(5):
        e = await ledger.append_event(
            event_type=EventType.TRUTH_CHANGE,
            actor=f"actor-{i}",
            actor_type=ActorType.HUMAN,
            action_summary=f"Entry {i}",
        )
        entries.append(e)

    assert await ledger.verify_integrity(entries=entries) is True


async def test_verify_integrity_empty_chain(ledger):
    """verify_integrity returns True for empty chain."""
    assert await ledger.verify_integrity(entries=[]) is True


async def test_verify_integrity_tampered_hash(ledger):
    """verify_integrity returns False if an entry's hash is tampered."""
    entries = []
    for i in range(3):
        e = await ledger.append_event(
            event_type=EventType.TRUTH_CHANGE,
            actor=f"actor-{i}",
            actor_type=ActorType.HUMAN,
            action_summary=f"Entry {i}",
        )
        entries.append(e)

    # Tamper with the second entry's hash
    tampered = entries[1].model_copy(update={"entry_hash": "deadbeef" * 8})
    tampered_chain = [entries[0], tampered, entries[2]]

    assert await ledger.verify_integrity(entries=tampered_chain) is False


async def test_verify_integrity_disrupted_order(ledger):
    """verify_integrity returns False if chain order is disrupted."""
    entries = []
    for i in range(3):
        e = await ledger.append_event(
            event_type=EventType.TRUTH_CHANGE,
            actor=f"actor-{i}",
            actor_type=ActorType.HUMAN,
            action_summary=f"Entry {i}",
        )
        entries.append(e)

    # Swap entries 1 and 2
    disrupted_chain = [entries[0], entries[2], entries[1]]

    assert await ledger.verify_integrity(entries=disrupted_chain) is False


# ---------------------------------------------------------------------------
# All EventType values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type", list(EventType))
async def test_append_event_all_event_types(ledger, event_type: EventType):
    """append_event works for every EventType value."""
    entry = await ledger.append_event(
        event_type=event_type,
        actor="test-actor",
        actor_type=ActorType.HUMAN,
        action_summary=f"Testing {event_type.value}",
    )

    assert entry.event_type == event_type
    assert entry.entry_hash is not None


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------


async def test_record_state_transition(ledger):
    """record_state_transition creates entry with event_type=STATE_TRANSITION."""
    entry = await ledger.record_state_transition(
        manifest_id="M-001",
        actor="system",
        actor_type=ActorType.CONTROL_PLANE,
        from_state="queued",
        to_state="in_flight",
        rationale="Auto transition",
    )

    assert entry.event_type == EventType.STATE_TRANSITION
    assert entry.previous_state == "queued"
    assert entry.new_state == "in_flight"
    assert "M-001" in entry.scope.affected_manifests
    assert "queued" in entry.action_summary
    assert "in_flight" in entry.action_summary


async def test_record_approval(ledger):
    """record_approval creates entry with event_type=APPROVAL."""
    entry = await ledger.record_approval(
        manifest_id="M-001",
        actor="reviewer",
        decision="approve",
        rationale="Code looks good",
    )

    assert entry.event_type == EventType.APPROVAL
    assert entry.actor == "reviewer"
    assert entry.actor_type == ActorType.HUMAN
    assert entry.decision == "approve"
    assert entry.rationale == "Code looks good"
    assert "M-001" in entry.scope.affected_manifests


async def test_record_invalidation(ledger):
    """record_invalidation creates entry with event_type=INVALIDATION and invalidation_severity."""
    entry = await ledger.record_invalidation(
        artifact_id="art-001",
        affected_manifests=("M-001", "M-002"),
        severity=InvalidationSeverity.HIGH,
        rationale="Truth artifact changed",
    )

    assert entry.event_type == EventType.INVALIDATION
    assert entry.invalidation_severity == InvalidationSeverity.HIGH
    assert entry.actor == "control_plane"
    assert entry.actor_type == ActorType.CONTROL_PLANE
    assert "art-001" in entry.scope.affected_artifacts
    assert entry.scope.affected_manifests == ("M-001", "M-002")


async def test_record_truth_change(ledger):
    """record_truth_change creates entry with event_type=TRUTH_CHANGE."""
    entry = await ledger.record_truth_change(
        artifact_id="art-001",
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Updated vision anchor",
    )

    assert entry.event_type == EventType.TRUTH_CHANGE
    assert "art-001" in entry.scope.affected_artifacts


async def test_record_classification(ledger):
    """record_classification creates entry with event_type=CLASSIFICATION."""
    entry = await ledger.record_classification(
        manifest_id="M-001",
        actor="classifier-agent",
        actor_type=ActorType.AGENT,
        classification_summary="Classified as Tier B, BC2, Class 3",
    )

    assert entry.event_type == EventType.CLASSIFICATION
    assert "M-001" in entry.scope.affected_manifests
    assert entry.actor == "classifier-agent"


# ---------------------------------------------------------------------------
# No update/delete
# ---------------------------------------------------------------------------


def test_no_update_method_exists(ledger):
    """AuditLedgerService has no update method."""
    assert not hasattr(ledger, "update")
    assert not hasattr(ledger, "update_event")
    assert not hasattr(ledger, "update_entry")


def test_no_delete_method_exists(ledger):
    """AuditLedgerService has no delete method."""
    assert not hasattr(ledger, "delete")
    assert not hasattr(ledger, "delete_event")
    assert not hasattr(ledger, "delete_entry")


# ---------------------------------------------------------------------------
# Query methods require repository
# ---------------------------------------------------------------------------


async def test_query_without_repository_raises(ledger):
    """Query methods raise RuntimeError when no repository is configured."""
    with pytest.raises(RuntimeError, match="Repository not configured"):
        await ledger.query_by_event_type(EventType.APPROVAL)

    with pytest.raises(RuntimeError, match="Repository not configured"):
        await ledger.query_by_actor("admin")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="Repository not configured"):
        await ledger.query_by_time_range(now, now)


# ---------------------------------------------------------------------------
# Optional metadata fields
# ---------------------------------------------------------------------------


async def test_append_event_with_cost_impact(ledger):
    """append_event accepts optional cost_impact metadata."""
    cost = CostImpact(
        tokens_consumed=1500,
        tasks_invalidated=2,
        rework_estimated_hours=4.5,
    )
    entry = await ledger.append_event(
        event_type=EventType.INVALIDATION,
        actor="control_plane",
        actor_type=ActorType.CONTROL_PLANE,
        action_summary="Invalidation with cost impact",
        cost_impact=cost,
    )

    assert entry.cost_impact is not None
    assert entry.cost_impact.tokens_consumed == 1500


async def test_append_event_with_model_version(ledger):
    """append_event accepts optional model_version metadata."""
    entry = await ledger.append_event(
        event_type=EventType.CLASSIFICATION,
        actor="classifier",
        actor_type=ActorType.AGENT,
        action_summary="Classification with model version",
        model_version="claude-3-opus-20240229",
    )

    assert entry.model_version == "claude-3-opus-20240229"


async def test_append_event_with_evidence_refs(ledger):
    """append_event accepts optional evidence_refs."""
    entry = await ledger.append_event(
        event_type=EventType.APPROVAL,
        actor="reviewer",
        actor_type=ActorType.HUMAN,
        action_summary="Approval with evidence",
        evidence_refs=("EP-001", "EP-002"),
    )

    assert entry.evidence_refs == ("EP-001", "EP-002")


# ---------------------------------------------------------------------------
# _row_to_entry conversion tests
# ---------------------------------------------------------------------------


def test_row_to_entry_basic_conversion():
    """_row_to_entry converts a mock DB row to an AuditEntry domain model."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        entry_id="AE-abc123def456",
        timestamp=now,
        event_type="truth_change",
        actor="admin",
        actor_type="human",
        scope={"affected_artifacts": ("art-1",), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Updated vision anchor",
        decision="create",
        rationale="Initial setup",
        metadata_extra={},
        prev_hash="GENESIS",
        entry_hash="a" * 64,
    )

    entry = AuditLedgerService._row_to_entry(row)

    assert isinstance(entry, AuditEntry)
    assert entry.entry_id == "AE-abc123def456"
    assert entry.event_type == EventType.TRUTH_CHANGE
    assert entry.actor == "admin"
    assert entry.actor_type == ActorType.HUMAN
    assert entry.scope.affected_artifacts == ("art-1",)
    assert entry.prev_hash == "GENESIS"
    assert entry.entry_hash == "a" * 64


def test_row_to_entry_with_metadata():
    """_row_to_entry extracts metadata_extra fields into AuditEntry."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        entry_id="AE-meta12345678",
        timestamp=now,
        event_type="state_transition",
        actor="system",
        actor_type="control_plane",
        scope={"affected_artifacts": (), "affected_tasks": (), "affected_manifests": ("M-001",)},
        action_summary="Transition",
        decision="transition",
        rationale="Auto",
        metadata_extra={
            "previous_state": "queued",
            "new_state": "in_flight",
            "evidence_refs": ("EP-001",),
            "model_version": "claude-3-opus",
        },
        prev_hash="prev123",
        entry_hash="b" * 64,
    )

    entry = AuditLedgerService._row_to_entry(row)

    assert entry.previous_state == "queued"
    assert entry.new_state == "in_flight"
    assert entry.evidence_refs == ("EP-001",)
    assert entry.model_version == "claude-3-opus"


def test_row_to_entry_with_invalidation_severity():
    """_row_to_entry converts invalidation_severity from metadata_extra."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        entry_id="AE-inv123456789",
        timestamp=now,
        event_type="invalidation",
        actor="control_plane",
        actor_type="control_plane",
        scope={"affected_artifacts": ("art-1",), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Invalidated",
        decision="invalidate",
        rationale="Changed",
        metadata_extra={"invalidation_severity": "high"},
        prev_hash="prev456",
        entry_hash="c" * 64,
    )

    entry = AuditLedgerService._row_to_entry(row)

    assert entry.invalidation_severity == InvalidationSeverity.HIGH


def test_row_to_entry_with_no_metadata_extra():
    """_row_to_entry handles missing metadata_extra attribute gracefully."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        entry_id="AE-nometa123456",
        timestamp=now,
        event_type="approval",
        actor="reviewer",
        actor_type="human",
        scope={"affected_artifacts": (), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Approved",
        decision="approve",
        rationale="LGTM",
        prev_hash="GENESIS",
        entry_hash="d" * 64,
    )
    # No metadata_extra attribute at all

    entry = AuditLedgerService._row_to_entry(row)

    assert entry.evidence_refs == ()
    assert entry.previous_state is None
    assert entry.new_state is None
    assert entry.invalidation_severity is None
    assert entry.model_version is None


# ---------------------------------------------------------------------------
# Query methods with mock repository
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_repository():
    """Create a mock AuditRepository."""
    from unittest.mock import AsyncMock, MagicMock

    repo = MagicMock()
    repo.get_by_event_type = AsyncMock(return_value=[])
    repo.get_by_actor = AsyncMock(return_value=[])
    repo.get_by_time_range = AsyncMock(return_value=[])
    repo.get_latest = AsyncMock(return_value=[])
    repo.get_last_entry = AsyncMock(return_value=None)
    repo.append = AsyncMock()
    return repo


@pytest.fixture()
def ledger_with_repo(mock_repository):
    """Create an AuditLedgerService with a mock repository."""
    from ces.control.services.audit_ledger import AuditLedgerService

    return AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=mock_repository)


def _make_mock_row(
    entry_id: str = "AE-query1234567",
    event_type: str = "approval",
    actor: str = "reviewer",
):
    """Create a mock AuditEntryRow for query results."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    return SimpleNamespace(
        entry_id=entry_id,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        actor=actor,
        actor_type="human",
        scope={"affected_artifacts": (), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Test action",
        decision="approve",
        rationale="Test",
        metadata_extra={},
        prev_hash="GENESIS",
        entry_hash="e" * 64,
    )


async def test_query_by_event_type_with_repository(ledger_with_repo, mock_repository):
    """query_by_event_type delegates to repository and converts rows."""
    row = _make_mock_row(event_type="approval")
    mock_repository.get_by_event_type.return_value = [row]

    results = await ledger_with_repo.query_by_event_type(EventType.APPROVAL)

    assert len(results) == 1
    assert isinstance(results[0], AuditEntry)
    assert results[0].event_type == EventType.APPROVAL
    mock_repository.get_by_event_type.assert_called_once_with("approval", project_id=None)


async def test_query_by_event_type_respects_limit(ledger_with_repo, mock_repository):
    """query_by_event_type returns at most 'limit' entries."""
    rows = [_make_mock_row(entry_id=f"AE-lim{i:09d}") for i in range(10)]
    mock_repository.get_by_event_type.return_value = rows

    results = await ledger_with_repo.query_by_event_type(EventType.APPROVAL, limit=3)

    assert len(results) == 3


async def test_query_by_actor_with_repository(ledger_with_repo, mock_repository):
    """query_by_actor delegates to repository and converts rows."""
    row = _make_mock_row(actor="agent-1")
    mock_repository.get_by_actor.return_value = [row]

    results = await ledger_with_repo.query_by_actor("agent-1")

    assert len(results) == 1
    assert results[0].actor == "agent-1"
    mock_repository.get_by_actor.assert_called_once_with("agent-1", project_id=None)


async def test_query_by_time_range_with_repository(ledger_with_repo, mock_repository):
    """query_by_time_range delegates to repository and converts rows."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=1)
    end = now

    row = _make_mock_row()
    mock_repository.get_by_time_range.return_value = [row]

    results = await ledger_with_repo.query_by_time_range(start, end)

    assert len(results) == 1
    assert isinstance(results[0], AuditEntry)
    mock_repository.get_by_time_range.assert_called_once_with(start, end, project_id=None)


async def test_query_by_actor_respects_limit(ledger_with_repo, mock_repository):
    """query_by_actor returns at most 'limit' entries."""
    rows = [_make_mock_row(entry_id=f"AE-act{i:09d}") for i in range(10)]
    mock_repository.get_by_actor.return_value = rows

    results = await ledger_with_repo.query_by_actor("reviewer", limit=5)

    assert len(results) == 5


# ---------------------------------------------------------------------------
# verify_integrity with repository
# ---------------------------------------------------------------------------


async def test_verify_integrity_with_repository(ledger_with_repo, mock_repository):
    """verify_integrity fetches entries from repository when no entries provided."""
    # Empty repository should return True
    mock_repository.get_latest.return_value = []

    result = await ledger_with_repo.verify_integrity()

    assert result is True
    mock_repository.get_latest.assert_called_once()


async def test_verify_integrity_forwards_project_id(ledger_with_repo, mock_repository):
    """verify_integrity passes project_id to repository-backed verification."""
    mock_repository.get_latest.return_value = []

    result = await ledger_with_repo.verify_integrity(project_id="proj-abc")

    assert result is True
    mock_repository.get_latest.assert_called_once_with(limit=10000, project_id="proj-abc")


async def test_verify_integrity_single_entry(ledger):
    """verify_integrity returns True for a single valid entry."""
    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Single entry",
    )

    assert await ledger.verify_integrity(entries=[entry]) is True


# ---------------------------------------------------------------------------
# append_event with repository persistence
# ---------------------------------------------------------------------------


async def test_append_event_persists_to_repository(ledger_with_repo, mock_repository):
    """append_event calls repository.append when a repository is configured."""
    entry = await ledger_with_repo.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Persisted entry",
        decision="create",
        rationale="Test persistence",
    )

    assert entry.entry_hash is not None
    mock_repository.append.assert_called_once()
    appended_row = mock_repository.append.call_args[0][0]
    assert appended_row.entry_id == entry.entry_id
    assert appended_row.entry_hash == entry.entry_hash


async def test_get_last_hash_from_repository(mock_repository):
    """_get_last_hash returns the hash from the repository's last entry."""
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    mock_last = SimpleNamespace(entry_hash="repo_last_hash_" + "0" * 50)
    mock_repository.get_last_entry.return_value = mock_last

    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=mock_repository)
    last_hash = await service._get_last_hash()

    assert last_hash == "repo_last_hash_" + "0" * 50


async def test_get_last_hash_from_repository_forwards_project_id(mock_repository):
    """_get_last_hash requests the latest entry for the current project scope."""
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    mock_last = SimpleNamespace(entry_hash="repo_project_hash_" + "1" * 47)
    mock_repository.get_last_entry.return_value = mock_last

    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=mock_repository)
    last_hash = await service._get_last_hash(project_id="proj-abc")

    assert last_hash == "repo_project_hash_" + "1" * 47
    mock_repository.get_last_entry.assert_called_once_with(project_id="proj-abc")


async def test_project_hash_heads_do_not_cross_contaminate_when_repository_has_no_rows(mock_repository):
    """A new project starts at GENESIS even after another project appended."""
    from ces.control.services.audit_ledger import AuditLedgerService

    service = AuditLedgerService(secret_key=TEST_SECRET_KEY, repository=mock_repository)

    first = await service.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Project A event",
        project_id="proj-a",
    )
    second = await service.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Project B event",
        project_id="proj-b",
    )

    assert first.prev_hash == "GENESIS"
    assert second.prev_hash == "GENESIS"


# ---------------------------------------------------------------------------
# project_id support (v1.2 MULTI-04)
# ---------------------------------------------------------------------------


async def test_append_event_with_project_id(ledger):
    """append_event sets project_id on the returned AuditEntry."""
    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Project-scoped entry",
        project_id="proj-abc123",
    )

    assert entry.project_id == "proj-abc123"


async def test_append_event_default_project_id(ledger):
    """append_event without project_id resolves to 'default' on the entry."""
    entry = await ledger.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Default project entry",
    )

    assert entry.project_id == "default"


async def test_append_event_uses_configured_default_project_id(mock_repository):
    """A service-level project_id scopes events when calls omit project_id."""
    from ces.control.services.audit_ledger import AuditLedgerService

    service = AuditLedgerService(
        secret_key=TEST_SECRET_KEY,
        repository=mock_repository,
        project_id="proj-configured",
    )

    entry = await service.append_event(
        event_type=EventType.TRUTH_CHANGE,
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Configured project event",
    )

    assert entry.project_id == "proj-configured"


async def test_append_event_persists_project_id_to_row(ledger_with_repo, mock_repository):
    """append_event writes project_id to the AuditEntryRow when persisting."""
    await ledger_with_repo.append_event(
        event_type=EventType.APPROVAL,
        actor="reviewer",
        actor_type=ActorType.HUMAN,
        action_summary="Scoped approval",
        project_id="proj-xyz789",
    )

    mock_repository.append.assert_called_once()
    row = mock_repository.append.call_args[0][0]
    assert row.project_id == "proj-xyz789"


async def test_append_event_persists_default_project_id_to_row(ledger_with_repo, mock_repository):
    """append_event writes project_id='default' to row when no project_id provided."""
    await ledger_with_repo.append_event(
        event_type=EventType.APPROVAL,
        actor="reviewer",
        actor_type=ActorType.HUMAN,
        action_summary="Unscoped approval",
    )

    mock_repository.append.assert_called_once()
    row = mock_repository.append.call_args[0][0]
    assert row.project_id == "default"


async def test_record_approval_forwards_project_id(ledger):
    """record_approval forwards project_id to append_event."""
    entry = await ledger.record_approval(
        manifest_id="M-001",
        actor="reviewer",
        decision="approve",
        rationale="LGTM",
        project_id="proj-test",
    )

    assert entry.project_id == "proj-test"


async def test_record_state_transition_forwards_project_id(ledger):
    """record_state_transition forwards project_id to append_event."""
    entry = await ledger.record_state_transition(
        manifest_id="M-001",
        actor="system",
        actor_type=ActorType.CONTROL_PLANE,
        from_state="queued",
        to_state="in_flight",
        project_id="proj-test",
    )

    assert entry.project_id == "proj-test"


async def test_record_invalidation_forwards_project_id(ledger):
    """record_invalidation forwards project_id to append_event."""
    entry = await ledger.record_invalidation(
        artifact_id="art-001",
        affected_manifests=("M-001",),
        severity=InvalidationSeverity.HIGH,
        rationale="Changed",
        project_id="proj-test",
    )

    assert entry.project_id == "proj-test"


async def test_record_truth_change_forwards_project_id(ledger):
    """record_truth_change forwards project_id to append_event."""
    entry = await ledger.record_truth_change(
        artifact_id="art-001",
        actor="admin",
        actor_type=ActorType.HUMAN,
        action_summary="Updated",
        project_id="proj-test",
    )

    assert entry.project_id == "proj-test"


async def test_record_classification_forwards_project_id(ledger):
    """record_classification forwards project_id to append_event."""
    entry = await ledger.record_classification(
        manifest_id="M-001",
        actor="classifier",
        actor_type=ActorType.AGENT,
        classification_summary="Tier B",
        project_id="proj-test",
    )

    assert entry.project_id == "proj-test"


async def test_query_by_event_type_forwards_project_id(ledger_with_repo, mock_repository):
    """query_by_event_type passes project_id to repository."""
    mock_repository.get_by_event_type.return_value = []

    await ledger_with_repo.query_by_event_type(EventType.APPROVAL, project_id="proj-abc")

    mock_repository.get_by_event_type.assert_called_once_with("approval", project_id="proj-abc")


async def test_query_by_actor_forwards_project_id(ledger_with_repo, mock_repository):
    """query_by_actor passes project_id to repository."""
    mock_repository.get_by_actor.return_value = []

    await ledger_with_repo.query_by_actor("admin", project_id="proj-abc")

    mock_repository.get_by_actor.assert_called_once_with("admin", project_id="proj-abc")


async def test_query_by_time_range_forwards_project_id(ledger_with_repo, mock_repository):
    """query_by_time_range passes project_id to repository."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    mock_repository.get_by_time_range.return_value = []

    await ledger_with_repo.query_by_time_range(now, now, project_id="proj-abc")

    mock_repository.get_by_time_range.assert_called_once_with(now, now, project_id="proj-abc")


def test_row_to_entry_extracts_project_id():
    """_row_to_entry extracts project_id from the DB row."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        entry_id="AE-proj12345678",
        timestamp=now,
        event_type="approval",
        actor="reviewer",
        actor_type="human",
        scope={"affected_artifacts": (), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Scoped",
        decision="approve",
        rationale="OK",
        metadata_extra={},
        project_id="proj-from-db",
        prev_hash="GENESIS",
        entry_hash="f" * 64,
    )

    entry = AuditLedgerService._row_to_entry(row)

    assert entry.project_id == "proj-from-db"


def test_row_to_entry_rehydrates_cost_impact():
    """Persisted cost metadata must participate in integrity recomputation."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from ces.control.services.audit_ledger import AuditLedgerService

    row = SimpleNamespace(
        entry_id="AE-cost1234567",
        timestamp=datetime.now(timezone.utc),
        event_type="approval",
        actor="reviewer",
        actor_type="human",
        scope={"affected_artifacts": (), "affected_tasks": (), "affected_manifests": ()},
        action_summary="Scoped",
        decision="approve",
        rationale="OK",
        metadata_extra={"cost_impact": {"tokens_consumed": 1200, "tasks_invalidated": 2}},
        project_id="proj-from-db",
        prev_hash="GENESIS",
        entry_hash="f" * 64,
    )

    entry = AuditLedgerService._row_to_entry(row)

    assert entry.cost_impact is not None
    assert entry.cost_impact.tokens_consumed == 1200
    assert entry.cost_impact.tasks_invalidated == 2


# ---------------------------------------------------------------------------
# Spec lifecycle event types (Phase 0 — schema foundations)
# ---------------------------------------------------------------------------


def test_spec_event_types_present():
    assert EventType.SPEC_AUTHORED.value == "spec_authored"
    assert EventType.SPEC_DECOMPOSED.value == "spec_decomposed"
    assert EventType.SPEC_RECONCILED.value == "spec_reconciled"
