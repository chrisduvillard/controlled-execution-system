"""Unit tests for KillSwitchService, KillSwitchState, ActivityClass, and KillSwitchProtocol.

Tests cover:
- ActivityClass enum completeness (7 values)
- KillSwitchState frozen dataclass behavior
- KillSwitchStateRow table definition
- KillSwitchService hard enforcement (is_halted)
- Per-activity-class halting and recovery
- Automatic trigger detection
- Audit ledger integration
- KillSwitchProtocol compliance
- KillSwitchRepository basic API

All tests run in-memory (no database) unless marked otherwise.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Task 1: Model + Enum + DB table tests
# ---------------------------------------------------------------------------


class TestActivityClassEnum:
    """Tests for ActivityClass enum completeness."""

    def test_activity_class_enum_has_seven_values(self):
        """ActivityClass enum must have exactly 7 values per D-05."""
        from ces.control.models.kill_switch_state import ActivityClass

        assert len(ActivityClass) == 7

    def test_activity_class_enum_values(self):
        """ActivityClass enum has the correct string values."""
        from ces.control.models.kill_switch_state import ActivityClass

        expected = {
            "task_issuance",
            "merges",
            "deploys",
            "spawning",
            "tool_classes",
            "truth_writes",
            "registry_writes",
        }
        actual = {member.value for member in ActivityClass}
        assert actual == expected

    def test_activity_class_is_str_enum(self):
        """ActivityClass members are strings (str, Enum)."""
        from ces.control.models.kill_switch_state import ActivityClass

        assert isinstance(ActivityClass.TASK_ISSUANCE, str)
        assert ActivityClass.TASK_ISSUANCE == "task_issuance"

    def test_activity_class_member_names(self):
        """ActivityClass has correctly named members."""
        from ces.control.models.kill_switch_state import ActivityClass

        assert hasattr(ActivityClass, "TASK_ISSUANCE")
        assert hasattr(ActivityClass, "MERGES")
        assert hasattr(ActivityClass, "DEPLOYS")
        assert hasattr(ActivityClass, "SPAWNING")
        assert hasattr(ActivityClass, "TOOL_CLASSES")
        assert hasattr(ActivityClass, "TRUTH_WRITES")
        assert hasattr(ActivityClass, "REGISTRY_WRITES")


class TestKillSwitchState:
    """Tests for KillSwitchState frozen dataclass."""

    def test_kill_switch_state_creation(self):
        """KillSwitchState can be created with minimal args."""
        from ces.control.models.kill_switch_state import (
            ActivityClass,
            KillSwitchState,
        )

        state = KillSwitchState(activity_class=ActivityClass.MERGES)
        assert state.activity_class == ActivityClass.MERGES

    def test_kill_switch_state_defaults_halted_false(self):
        """KillSwitchState defaults halted=False."""
        from ces.control.models.kill_switch_state import (
            ActivityClass,
            KillSwitchState,
        )

        state = KillSwitchState(activity_class=ActivityClass.DEPLOYS)
        assert state.halted is False

    def test_kill_switch_state_defaults_optional_none(self):
        """KillSwitchState defaults optional fields to None."""
        from ces.control.models.kill_switch_state import (
            ActivityClass,
            KillSwitchState,
        )

        state = KillSwitchState(activity_class=ActivityClass.DEPLOYS)
        assert state.halted_by is None
        assert state.halted_at is None
        assert state.reason is None

    def test_kill_switch_state_frozen(self):
        """KillSwitchState is frozen (immutable)."""
        from ces.control.models.kill_switch_state import (
            ActivityClass,
            KillSwitchState,
        )

        state = KillSwitchState(activity_class=ActivityClass.MERGES)
        with pytest.raises(AttributeError):
            state.halted = True  # type: ignore[misc]

    def test_kill_switch_state_with_all_fields(self):
        """KillSwitchState can be created with all fields."""
        from ces.control.models.kill_switch_state import (
            ActivityClass,
            KillSwitchState,
        )

        state = KillSwitchState(
            activity_class=ActivityClass.SPAWNING,
            halted=True,
            halted_by="admin",
            halted_at="2026-04-06T12:00:00Z",
            reason="safety concern",
        )
        assert state.halted is True
        assert state.halted_by == "admin"
        assert state.halted_at == "2026-04-06T12:00:00Z"
        assert state.reason == "safety concern"


class TestKillSwitchStateRow:
    """Tests for KillSwitchStateRow SQLAlchemy table definition."""

    def test_kill_switch_state_row_exists(self):
        """KillSwitchStateRow class is importable from tables module."""
        from tests.integration._compat.control_db.tables import KillSwitchStateRow

        assert KillSwitchStateRow is not None

    def test_kill_switch_state_row_tablename(self):
        """KillSwitchStateRow has correct __tablename__."""
        from tests.integration._compat.control_db.tables import KillSwitchStateRow

        assert KillSwitchStateRow.__tablename__ == "kill_switch_state"

    def test_kill_switch_state_row_schema(self):
        """KillSwitchStateRow uses control schema."""
        from tests.integration._compat.control_db.tables import KillSwitchStateRow

        assert KillSwitchStateRow.__table__.schema == "control"

    def test_kill_switch_state_row_columns(self):
        """KillSwitchStateRow has required columns."""
        from tests.integration._compat.control_db.tables import KillSwitchStateRow

        columns = {c.name for c in KillSwitchStateRow.__table__.columns}
        required = {"activity_class", "halted", "halted_by", "halted_at", "reason", "updated_at"}
        assert required.issubset(columns)

    def test_kill_switch_state_row_primary_key(self):
        """KillSwitchStateRow primary key is activity_class."""
        from tests.integration._compat.control_db.tables import KillSwitchStateRow

        pk_columns = [c.name for c in KillSwitchStateRow.__table__.primary_key.columns]
        assert pk_columns == ["activity_class"]


class TestKillSwitchRepository:
    """Tests for KillSwitchRepository class existence."""

    def test_kill_switch_repository_exists(self):
        """KillSwitchRepository class is importable from repository module."""
        from tests.integration._compat.control_db.repository import KillSwitchRepository

        assert KillSwitchRepository is not None

    def test_kill_switch_repository_has_required_methods(self):
        """KillSwitchRepository has all required methods."""
        from tests.integration._compat.control_db.repository import KillSwitchRepository

        assert hasattr(KillSwitchRepository, "get_all")
        assert hasattr(KillSwitchRepository, "get_by_activity_class")
        assert hasattr(KillSwitchRepository, "upsert")
        assert hasattr(KillSwitchRepository, "initialize_defaults")


class TestModelReExports:
    """Tests for model re-exports in __init__.py."""

    def test_activity_class_reexported(self):
        """ActivityClass is re-exported from models package."""
        from ces.control.models import ActivityClass

    def test_kill_switch_state_reexported(self):
        """KillSwitchState is re-exported from models package."""
        from ces.control.models import KillSwitchState


# ---------------------------------------------------------------------------
# Task 2: KillSwitchService, KillSwitchProtocol, auto-triggers, audit logging
# ---------------------------------------------------------------------------


class MockAuditLedger:
    """Mock audit ledger that records append_event calls for testing."""

    def __init__(self):
        self.events: list[dict] = []

    async def append_event(self, **kwargs):
        self.events.append(kwargs)


@pytest.fixture()
def kill_switch_service():
    """Create an in-memory KillSwitchService with no repository and no audit_ledger."""
    from ces.control.services.kill_switch import KillSwitchService

    return KillSwitchService()


@pytest.fixture()
def kill_switch_service_with_audit():
    """Create KillSwitchService with a mock audit ledger."""
    from ces.control.services.kill_switch import KillSwitchService

    audit = MockAuditLedger()
    service = KillSwitchService(audit_ledger=audit)
    return service, audit


class TestKillSwitchProtocol:
    """Tests for KillSwitchProtocol definition and compliance."""

    def test_kill_switch_protocol_exists(self):
        """KillSwitchProtocol is importable."""
        from ces.control.services.kill_switch import KillSwitchProtocol

        assert KillSwitchProtocol is not None

    def test_kill_switch_protocol_is_runtime_checkable(self):
        """KillSwitchProtocol is runtime checkable."""
        from ces.control.services.kill_switch import (
            KillSwitchProtocol,
            KillSwitchService,
        )

        service = KillSwitchService()
        assert isinstance(service, KillSwitchProtocol)

    def test_kill_switch_protocol_defines_is_halted(self):
        """KillSwitchProtocol defines is_halted method."""
        from ces.control.services.kill_switch import KillSwitchProtocol

        assert hasattr(KillSwitchProtocol, "is_halted")


class TestKillSwitchServiceBasic:
    """Tests for KillSwitchService basic functionality."""

    def test_is_halted_default_false(self, kill_switch_service):
        """is_halted returns False by default for all activity classes."""
        assert kill_switch_service.is_halted("merges") is False

    def test_is_halted_all_classes_default_false(self, kill_switch_service):
        """All 7 activity classes default to not halted."""
        from ces.control.models.kill_switch_state import ActivityClass

        for ac in ActivityClass:
            assert kill_switch_service.is_halted(ac.value) is False

    async def test_halt_activity(self, kill_switch_service):
        """After activate, is_halted returns True."""
        from ces.control.models.kill_switch_state import ActivityClass

        result = await kill_switch_service.activate(ActivityClass.MERGES, actor="admin", reason="safety")
        assert kill_switch_service.is_halted("merges") is True
        assert result.halted is True
        assert result.activity_class == ActivityClass.MERGES

    async def test_recover_activity(self, kill_switch_service):
        """After activate then recover, is_halted returns False."""
        from ces.control.models.kill_switch_state import ActivityClass

        await kill_switch_service.activate(ActivityClass.MERGES, actor="admin", reason="safety")
        result = await kill_switch_service.recover(ActivityClass.MERGES, actor="admin", reason="resolved")
        assert kill_switch_service.is_halted("merges") is False
        assert result.halted is False

    async def test_independent_activity_classes(self, kill_switch_service):
        """Activating one activity class does not affect others."""
        from ces.control.models.kill_switch_state import ActivityClass

        await kill_switch_service.activate(ActivityClass.MERGES, actor="admin", reason="safety")
        assert kill_switch_service.is_halted("merges") is True
        assert kill_switch_service.is_halted("deploys") is False
        assert kill_switch_service.is_halted("task_issuance") is False

    async def test_all_classes_independently_activatable(self, kill_switch_service):
        """All 7 activity classes can be independently activated and recovered."""
        from ces.control.models.kill_switch_state import ActivityClass

        # Activate all
        for ac in ActivityClass:
            await kill_switch_service.activate(ac, actor="admin", reason="test")
        for ac in ActivityClass:
            assert kill_switch_service.is_halted(ac.value) is True

        # Recover all
        for ac in ActivityClass:
            await kill_switch_service.recover(ac, actor="admin", reason="test")
        for ac in ActivityClass:
            assert kill_switch_service.is_halted(ac.value) is False

    def test_hard_enforcement_never_raises(self, kill_switch_service):
        """is_halted never raises exceptions -- always returns bool (D-06)."""
        # Test with valid activity class
        result = kill_switch_service.is_halted("merges")
        assert isinstance(result, bool)

        # Test with unknown activity class -- should return False, not raise
        result = kill_switch_service.is_halted("nonexistent_class")
        assert isinstance(result, bool)
        assert result is False

    def test_works_without_repository(self):
        """KillSwitchService works without a repository (in-memory only)."""
        from ces.control.services.kill_switch import KillSwitchService

        service = KillSwitchService(repository=None)
        assert service.is_halted("merges") is False

    def test_works_without_audit_ledger(self):
        """KillSwitchService works without an audit ledger."""
        from ces.control.services.kill_switch import KillSwitchService

        service = KillSwitchService(audit_ledger=None)
        assert service.is_halted("merges") is False


class TestKillSwitchAuditLogging:
    """Tests for audit ledger integration."""

    async def test_activate_logs_kill_switch_event(self, kill_switch_service_with_audit):
        """activate logs a KILL_SWITCH event to the audit ledger."""
        from ces.control.models.kill_switch_state import ActivityClass
        from ces.shared.enums import EventType

        service, audit = kill_switch_service_with_audit
        await service.activate(ActivityClass.MERGES, actor="admin", reason="safety concern")

        assert len(audit.events) == 1
        event = audit.events[0]
        assert event["event_type"] == EventType.KILL_SWITCH
        assert event["actor"] == "admin"
        assert "merges" in event["action_summary"].lower()

    async def test_recover_logs_recovery_event(self, kill_switch_service_with_audit):
        """recover logs a RECOVERY event to the audit ledger."""
        from ces.control.models.kill_switch_state import ActivityClass
        from ces.shared.enums import EventType

        service, audit = kill_switch_service_with_audit
        await service.activate(ActivityClass.MERGES, actor="admin", reason="safety")
        await service.recover(ActivityClass.MERGES, actor="admin", reason="resolved")

        assert len(audit.events) == 2
        recovery_event = audit.events[1]
        assert recovery_event["event_type"] == EventType.RECOVERY
        assert recovery_event["actor"] == "admin"

    async def test_activate_without_audit_ledger_succeeds(self, kill_switch_service):
        """activate works without audit ledger (no exception)."""
        from ces.control.models.kill_switch_state import ActivityClass

        result = await kill_switch_service.activate(ActivityClass.MERGES, actor="admin", reason="safety")
        assert result.halted is True


class TestKillSwitchAutoTriggers:
    """Tests for automatic trigger detection per KILL-02 and KILL-03."""

    async def test_auto_triggers_invalidation_engine_failure(self, kill_switch_service):
        """invalidation_engine_failure triggers truth_writes + registry_writes."""
        results = await kill_switch_service.check_auto_triggers("invalidation_engine_failure", {})
        assert kill_switch_service.is_halted("truth_writes") is True
        assert kill_switch_service.is_halted("registry_writes") is True
        assert len(results) >= 2

    async def test_auto_triggers_unexplained_truth_drift(self, kill_switch_service):
        """unexplained_truth_drift triggers truth_writes."""
        results = await kill_switch_service.check_auto_triggers("unexplained_truth_drift", {})
        assert kill_switch_service.is_halted("truth_writes") is True
        assert len(results) >= 1

    async def test_auto_triggers_recursive_delegation_explosion(self, kill_switch_service):
        """recursive_delegation_explosion triggers spawning."""
        results = await kill_switch_service.check_auto_triggers("recursive_delegation_explosion", {})
        assert kill_switch_service.is_halted("spawning") is True
        assert len(results) >= 1

    async def test_auto_triggers_sensor_pack_failure_high_risk(self, kill_switch_service):
        """sensor_pack_failure_high_risk triggers task_issuance."""
        results = await kill_switch_service.check_auto_triggers("sensor_pack_failure_high_risk", {})
        assert kill_switch_service.is_halted("task_issuance") is True
        assert len(results) >= 1

    async def test_auto_triggers_rising_escapes_green_checks(self, kill_switch_service):
        """rising_escapes_green_checks triggers merges + deploys."""
        results = await kill_switch_service.check_auto_triggers("rising_escapes_green_checks", {})
        assert kill_switch_service.is_halted("merges") is True
        assert kill_switch_service.is_halted("deploys") is True
        assert len(results) >= 2

    async def test_auto_triggers_unknown_returns_empty(self, kill_switch_service):
        """Unknown trigger type returns empty list without error."""
        results = await kill_switch_service.check_auto_triggers("unknown_trigger", {})
        assert results == []

    async def test_auto_triggers_already_halted_no_duplicate(self, kill_switch_service):
        """Auto-trigger on already-halted class does not create duplicate."""
        from ces.control.models.kill_switch_state import ActivityClass

        await kill_switch_service.activate(ActivityClass.TRUTH_WRITES, actor="admin", reason="manual")
        results = await kill_switch_service.check_auto_triggers("unexplained_truth_drift", {})
        # truth_writes already halted -- should still be halted but no new activation
        assert kill_switch_service.is_halted("truth_writes") is True
        assert len(results) == 0  # Already halted, no new activations


class TestKillSwitchPersistence:
    """activate/recover persist to the repository when one is configured."""

    async def test_activate_upserts_halted_row(self):
        from unittest.mock import AsyncMock

        from ces.control.models.kill_switch_state import ActivityClass
        from ces.control.services.kill_switch import KillSwitchService

        repo = AsyncMock()
        service = KillSwitchService(repository=repo)

        await service.activate(ActivityClass.MERGES, actor="admin", reason="safety")

        repo.upsert.assert_awaited_once()
        row = repo.upsert.await_args.args[0]
        assert row.activity_class == "merges"
        assert row.halted is True
        assert row.halted_by == "admin"
        assert row.reason == "safety"

    async def test_recover_upserts_cleared_row(self):
        from unittest.mock import AsyncMock

        from ces.control.models.kill_switch_state import ActivityClass
        from ces.control.services.kill_switch import KillSwitchService

        repo = AsyncMock()
        service = KillSwitchService(repository=repo)

        await service.recover(ActivityClass.MERGES, actor="admin", reason="resolved")

        repo.upsert.assert_awaited_once()
        row = repo.upsert.await_args.args[0]
        assert row.activity_class == "merges"
        assert row.halted is False
        assert row.halted_by is None
        assert row.halted_at is None
        assert row.reason is None


class TestKillSwitchLoadFromDb:
    """load_from_db hydrates the cache and tolerates unknown activity classes."""

    async def test_load_from_db_without_repository_raises(self):
        from ces.control.services.kill_switch import KillSwitchService

        service = KillSwitchService()
        with pytest.raises(RuntimeError, match="Repository not configured"):
            await service.load_from_db()

    async def test_load_from_db_populates_cache_and_skips_unknown(self):
        from datetime import datetime, timezone
        from unittest.mock import AsyncMock, MagicMock

        from ces.control.services.kill_switch import KillSwitchService

        halted_row = MagicMock()
        halted_row.activity_class = "merges"
        halted_row.halted = True
        halted_row.halted_by = "admin"
        halted_row.halted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        halted_row.reason = "safety"

        recovered_row = MagicMock()
        recovered_row.activity_class = "deploys"
        recovered_row.halted = False
        recovered_row.halted_by = None
        recovered_row.halted_at = None
        recovered_row.reason = None

        unknown_row = MagicMock()
        unknown_row.activity_class = "not_a_real_class"

        repo = AsyncMock()
        repo.get_all = AsyncMock(return_value=[halted_row, recovered_row, unknown_row])
        service = KillSwitchService(repository=repo)

        await service.load_from_db()

        assert service.is_halted("merges") is True
        assert service.is_halted("deploys") is False
        # Unknown activity class was skipped, not propagated as error.
        assert service.is_halted("not_a_real_class") is False


class TestKillSwitchServiceReExports:
    """Tests for service re-exports in __init__.py."""

    def test_kill_switch_service_reexported(self):
        """KillSwitchService is re-exported from services package."""
        from ces.control.services import KillSwitchService

    def test_kill_switch_protocol_reexported(self):
        """KillSwitchProtocol is re-exported from services package."""
        from ces.control.services import KillSwitchProtocol
