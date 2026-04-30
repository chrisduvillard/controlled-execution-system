"""Tests for CES GovernedArtifactBase and CESBaseModel.

Validates the governed artifact base model's fields, validation rules,
and the approved-requires-signature enforcement (MODEL-16).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ces.shared.base import CESBaseModel, GovernedArtifactBase
from ces.shared.enums import ArtifactStatus


class TestGovernedArtifactBase:
    """GovernedArtifactBase enforces governance rules on truth artifacts."""

    @pytest.fixture()
    def now(self) -> datetime:
        return datetime.now(tz=UTC)

    def test_draft_allows_none_signature(self, now: datetime) -> None:
        """Draft artifacts should not require a signature."""
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.signature is None
        assert artifact.status == ArtifactStatus.DRAFT

    def test_approved_requires_signature(self, now: datetime) -> None:
        """Approved artifacts MUST have a signature (MODEL-16)."""
        with pytest.raises(ValidationError, match="Approved artifacts must be signed"):
            GovernedArtifactBase(
                version=1,
                status=ArtifactStatus.APPROVED,
                owner="test-user",
                created_at=now,
                last_confirmed=now,
                signature=None,
            )

    def test_approved_with_signature_succeeds(self, now: datetime) -> None:
        """Approved artifacts with a valid signature should be created successfully."""
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.APPROVED,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
            signature="abc123signature",
            content_hash="deadbeef" * 8,
        )
        assert artifact.status == ArtifactStatus.APPROVED
        assert artifact.signature == "abc123signature"

    def test_has_version_field(self, now: datetime) -> None:
        """Version must be an integer >= 1."""
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.version == 1

    def test_version_minimum_enforced(self, now: datetime) -> None:
        """Version must be at least 1."""
        with pytest.raises(ValidationError):
            GovernedArtifactBase(
                version=0,
                status=ArtifactStatus.DRAFT,
                owner="test-user",
                created_at=now,
                last_confirmed=now,
            )

    def test_has_status_field(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert isinstance(artifact.status, ArtifactStatus)

    def test_has_owner_field(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.owner == "test-user"

    def test_has_created_at_field(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.created_at == now

    def test_has_last_confirmed_field(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.last_confirmed == now

    def test_has_optional_signature(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.signature is None

    def test_has_optional_content_hash(self, now: datetime) -> None:
        artifact = GovernedArtifactBase(
            version=1,
            status=ArtifactStatus.DRAFT,
            owner="test-user",
            created_at=now,
            last_confirmed=now,
        )
        assert artifact.content_hash is None

    def test_all_artifact_statuses_work_without_signature(self, now: datetime) -> None:
        """Non-approved statuses should not require signature."""
        for status in [
            ArtifactStatus.DRAFT,
            ArtifactStatus.SUPERSEDED,
            ArtifactStatus.DEFERRED,
            ArtifactStatus.RETIRED,
            ArtifactStatus.DEPRECATED,
        ]:
            artifact = GovernedArtifactBase(
                version=1,
                status=status,
                owner="test-user",
                created_at=now,
                last_confirmed=now,
            )
            assert artifact.status == status


class TestCESBaseModel:
    """CESBaseModel is a strict, frozen base for non-governed models."""

    def test_exists(self) -> None:
        """CESBaseModel should be importable."""
        assert CESBaseModel is not None
