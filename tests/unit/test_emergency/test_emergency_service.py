"""Tests for EmergencyService (EMERG-01 through EMERG-04).

Verifies:
- Emergency declaration creates manifest, activates kill switch, starts timer
- Emergency resolution recovers kill switch, schedules post-incident review
- Compensating controls: freeze, 24h review, retroactive evidence
- Single-emergency constraint
- Blast radius isolation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ces.control.models.kill_switch_state import ActivityClass
from ces.control.models.manifest import TaskManifest
from ces.emergency.services.emergency_service import EmergencyService
from ces.emergency.services.manifest_factory import EmergencyManifestFactory
from ces.emergency.services.sla_timer import SLATimerService
from ces.shared.enums import EventType, RiskTier


@pytest.fixture
def mock_kill_switch() -> MagicMock:
    """Create a mock kill switch."""
    ks = MagicMock()
    ks.is_halted = MagicMock(return_value=False)
    ks.activate = AsyncMock()
    ks.recover = AsyncMock()
    return ks


@pytest.fixture
def mock_audit_ledger() -> AsyncMock:
    """Create a mock audit ledger."""
    ledger = AsyncMock()
    ledger.append_event = AsyncMock()
    return ledger


@pytest.fixture
def sla_timer() -> SLATimerService:
    """Create an SLATimerService without Celery."""
    return SLATimerService()


@pytest.fixture
def service(
    mock_kill_switch: MagicMock,
    mock_audit_ledger: AsyncMock,
    sla_timer: SLATimerService,
) -> EmergencyService:
    """Create an EmergencyService with mocked dependencies."""
    return EmergencyService(
        kill_switch=mock_kill_switch,
        audit_ledger=mock_audit_ledger,
        sla_timer=sla_timer,
    )


class TestDeclareEmergency:
    """Tests for declare_emergency method."""

    @pytest.mark.asyncio
    async def test_uses_injected_manifest_factory(self) -> None:
        """declare_emergency uses the injected manifest factory dependency."""
        custom_manifest = EmergencyManifestFactory.create(
            description="Factory-produced hotfix",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )
        custom_factory = MagicMock()
        custom_factory.create.return_value = custom_manifest

        service = EmergencyService(manifest_factory=custom_factory)

        result = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        custom_factory.create.assert_called_once_with(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )
        assert result == custom_manifest

    @pytest.mark.asyncio
    async def test_creates_emergency_manifest(self, service: EmergencyService) -> None:
        """Test 6: EmergencyService.declare_emergency() creates emergency manifest via factory."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert isinstance(manifest, TaskManifest)
        assert manifest.manifest_id.startswith("EM-")
        assert manifest.risk_tier == RiskTier.A

    @pytest.mark.asyncio
    async def test_activates_kill_switch(self, service: EmergencyService, mock_kill_switch: MagicMock) -> None:
        """Test 7: declare_emergency activates kill switch for task_issuance."""
        await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        mock_kill_switch.activate.assert_called_once()
        call_args = mock_kill_switch.activate.call_args
        assert call_args[1]["activity_class"] == ActivityClass.TASK_ISSUANCE

    @pytest.mark.asyncio
    async def test_logs_to_audit_ledger(self, service: EmergencyService, mock_audit_ledger: AsyncMock) -> None:
        """Test 8: declare_emergency logs emergency declaration to audit ledger."""
        await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        mock_audit_ledger.append_event.assert_called()

    @pytest.mark.asyncio
    async def test_starts_sla_timer(self, service: EmergencyService, sla_timer: SLATimerService) -> None:
        """Test 9: declare_emergency starts SLA timer (15 min countdown)."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.manifest_id in sla_timer._deadlines

    @pytest.mark.asyncio
    async def test_returns_manifest(self, service: EmergencyService) -> None:
        """Test 10: declare_emergency returns the emergency manifest."""
        result = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert isinstance(result, TaskManifest)


class TestResolveEmergency:
    """Tests for resolve_emergency method."""

    @pytest.mark.asyncio
    async def test_recovers_kill_switch(self, service: EmergencyService, mock_kill_switch: MagicMock) -> None:
        """Test 11: resolve_emergency recovers kill switch."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        mock_kill_switch.recover.assert_called_once()
        call_args = mock_kill_switch.recover.call_args
        assert call_args[1]["activity_class"] == ActivityClass.TASK_ISSUANCE

    @pytest.mark.asyncio
    async def test_logs_resolution_to_audit(self, service: EmergencyService, mock_audit_ledger: AsyncMock) -> None:
        """Test 12: resolve_emergency logs resolution to audit ledger."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        # Reset call count after declaration
        mock_audit_ledger.append_event.reset_mock()

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        # Should have 3 audit calls: resolution, post-incident review, retroactive evidence
        assert mock_audit_ledger.append_event.call_count == 3

    @pytest.mark.asyncio
    async def test_schedules_post_incident_review(
        self, service: EmergencyService, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 13: resolve_emergency schedules post-incident review within 24h."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        mock_audit_ledger.append_event.reset_mock()

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        # Check that one of the audit calls is for post-incident review
        call_args_list = mock_audit_ledger.append_event.call_args_list
        escalation_calls = [c for c in call_args_list if c[1].get("event_type") == EventType.ESCALATION]
        assert len(escalation_calls) == 1
        assert "24h" in escalation_calls[0][1]["action_summary"]

    @pytest.mark.asyncio
    async def test_creates_retroactive_evidence_placeholder(
        self, service: EmergencyService, mock_audit_ledger: AsyncMock
    ) -> None:
        """Test 14: resolve_emergency creates retroactive evidence packet placeholder."""
        manifest = await service.declare_emergency(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        mock_audit_ledger.append_event.reset_mock()

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        call_args_list = mock_audit_ledger.append_event.call_args_list
        classification_calls = [c for c in call_args_list if c[1].get("event_type") == EventType.CLASSIFICATION]
        assert len(classification_calls) == 1
        assert "Retroactive evidence" in classification_calls[0][1]["action_summary"]


class TestBlastRadius:
    """Tests for blast radius isolation."""

    @pytest.mark.asyncio
    async def test_blast_radius_blocks_non_emergency(
        self, service: EmergencyService, mock_kill_switch: MagicMock
    ) -> None:
        """Test 18: declare_emergency with files blocks non-emergency manifests."""
        await service.declare_emergency(
            description="Fix payment bug",
            affected_files=["a.py", "b.py"],
            declared_by="ops-engineer",
        )

        # Kill switch was activated for TASK_ISSUANCE, blocking non-emergency work
        mock_kill_switch.activate.assert_called_once()
        call_args = mock_kill_switch.activate.call_args
        assert "blast radius" in call_args[1]["reason"].lower()


class TestSingleEmergencyConstraint:
    """Tests for single active emergency constraint."""

    @pytest.mark.asyncio
    async def test_only_one_active_emergency(self, service: EmergencyService) -> None:
        """Test 19: Only one active emergency allowed at a time."""
        await service.declare_emergency(
            description="First emergency",
            affected_files=["a.py"],
            declared_by="ops-engineer",
        )

        with pytest.raises(ValueError, match="Only one active emergency"):
            await service.declare_emergency(
                description="Second emergency",
                affected_files=["b.py"],
                declared_by="ops-engineer",
            )

    @pytest.mark.asyncio
    async def test_can_declare_after_resolution(self, service: EmergencyService) -> None:
        """After resolving, can declare a new emergency."""
        manifest = await service.declare_emergency(
            description="First emergency",
            affected_files=["a.py"],
            declared_by="ops-engineer",
        )

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        # Should not raise
        manifest2 = await service.declare_emergency(
            description="Second emergency",
            affected_files=["c.py"],
            declared_by="ops-engineer",
        )
        assert manifest2.manifest_id.startswith("EM-")

    @pytest.mark.asyncio
    async def test_is_emergency_active(self, service: EmergencyService) -> None:
        """is_emergency_active reflects state correctly."""
        assert service.is_emergency_active() is False

        manifest = await service.declare_emergency(
            description="Emergency",
            affected_files=["a.py"],
            declared_by="ops-engineer",
        )

        assert service.is_emergency_active() is True

        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-engineer",
        )

        assert service.is_emergency_active() is False


class TestEmergencyEdgeCases:
    """Tests for emergency service edge cases and error paths."""

    @pytest.mark.asyncio
    async def test_resolve_wrong_manifest_raises(self, service: EmergencyService) -> None:
        """resolve_emergency raises ValueError if manifest_id does not match active."""
        await service.declare_emergency(
            description="Real emergency",
            affected_files=["a.py"],
            declared_by="ops-engineer",
        )

        with pytest.raises(ValueError, match="not the active emergency"):
            await service.resolve_emergency(
                manifest_id="EM-nonexistent",
                resolved_by="ops-engineer",
            )

    @pytest.mark.asyncio
    async def test_declare_without_kill_switch(self) -> None:
        """declare_emergency works without kill_switch (None)."""
        audit = AsyncMock()
        audit.append_event = AsyncMock()

        svc = EmergencyService(kill_switch=None, audit_ledger=audit)
        manifest = await svc.declare_emergency(
            description="No kill switch",
            affected_files=["a.py"],
            declared_by="ops-engineer",
        )
        assert manifest.manifest_id.startswith("EM-")

    @pytest.mark.asyncio
    async def test_resolve_without_kill_switch(self) -> None:
        """resolve_emergency works without kill_switch (None)."""
        audit = AsyncMock()
        audit.append_event = AsyncMock()

        svc = EmergencyService(kill_switch=None, audit_ledger=audit)
        manifest = await svc.declare_emergency(
            description="Test",
            affected_files=["a.py"],
            declared_by="ops",
        )
        await svc.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops",
        )
        assert not svc.is_emergency_active()

    @pytest.mark.asyncio
    async def test_declare_without_audit_ledger(self) -> None:
        """declare_emergency works without audit_ledger (None)."""
        ks = MagicMock()
        ks.activate = AsyncMock()

        svc = EmergencyService(kill_switch=ks, audit_ledger=None)
        manifest = await svc.declare_emergency(
            description="No audit",
            affected_files=["a.py"],
            declared_by="ops",
        )
        assert manifest.manifest_id.startswith("EM-")

    @pytest.mark.asyncio
    async def test_resolve_without_audit_ledger(self) -> None:
        """resolve_emergency works without audit_ledger (None)."""
        ks = MagicMock()
        ks.activate = AsyncMock()
        ks.recover = AsyncMock()

        svc = EmergencyService(kill_switch=ks, audit_ledger=None)
        manifest = await svc.declare_emergency(
            description="No audit resolve",
            affected_files=["a.py"],
            declared_by="ops",
        )
        await svc.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops",
        )
        assert not svc.is_emergency_active()

    @pytest.mark.asyncio
    async def test_get_active_emergency_returns_id(self, service: EmergencyService) -> None:
        """get_active_emergency returns manifest_id when active."""
        assert service.get_active_emergency() is None

        manifest = await service.declare_emergency(
            description="Test",
            affected_files=["a.py"],
            declared_by="ops",
        )
        assert service.get_active_emergency() == manifest.manifest_id
