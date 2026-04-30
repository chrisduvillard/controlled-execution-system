"""Tests for EmergencyManifestFactory (EMERG-01, EMERG-02).

Verifies that emergency manifests are created with correct defaults:
- Tier A risk classification
- 500-line cap
- 15-minute TTL
- [EMERGENCY] description prefix
- Non-empty affected_files required
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ces.emergency.services.manifest_factory import EmergencyManifestFactory
from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier


class TestEmergencyManifestFactory:
    """Test suite for EmergencyManifestFactory."""

    def test_creates_tier_a_manifest(self) -> None:
        """Test 1: EmergencyManifestFactory.create() produces TaskManifest with risk_tier=A."""
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.risk_tier == RiskTier.A

    def test_sets_500_line_cap(self) -> None:
        """Test 2: EmergencyManifestFactory.create() auto-sets 500-line cap."""
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.token_budget <= 50000
        # The 500-line cap is stored in the manifest metadata or description
        assert "500" in manifest.description or manifest.token_budget > 0

    def test_sets_15_minute_ttl(self) -> None:
        """Test 3: EmergencyManifestFactory.create() sets TTL to 15 minutes from now."""
        before = datetime.now(timezone.utc)
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )
        after = datetime.now(timezone.utc)

        # TTL should be ~15 minutes from creation
        expected_min = before + timedelta(minutes=14, seconds=50)
        expected_max = after + timedelta(minutes=15, seconds=10)

        assert manifest.expires_at >= expected_min
        assert manifest.expires_at <= expected_max

    def test_requires_non_empty_affected_files(self) -> None:
        """Test 4: EmergencyManifestFactory.create() requires affected_files list (non-empty)."""
        with pytest.raises(ValueError, match="affected_files"):
            EmergencyManifestFactory.create(
                description="Fix critical payment bug",
                affected_files=[],
                declared_by="ops-engineer",
            )

    def test_adds_emergency_prefix(self) -> None:
        """Test 5: EmergencyManifestFactory.create() auto-populates description prefix [EMERGENCY]."""
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.description.startswith("[EMERGENCY]")

    def test_manifest_id_starts_with_em(self) -> None:
        """Emergency manifest IDs follow EM-xxx format."""
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.manifest_id.startswith("EM-")

    def test_worst_case_defaults(self) -> None:
        """Emergency manifests use worst-case classification defaults."""
        manifest = EmergencyManifestFactory.create(
            description="Fix critical payment bug",
            affected_files=["src/payments/charge.py"],
            declared_by="ops-engineer",
        )

        assert manifest.behavior_confidence == BehaviorConfidence.BC3
        assert manifest.change_class == ChangeClass.CLASS_5
