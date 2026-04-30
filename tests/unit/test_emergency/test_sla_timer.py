"""Tests for SLATimerService (EMERG-03).

Verifies:
- SLA timer scheduling with 900-second countdown
- Deadline breach detection
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from ces.emergency.services.sla_timer import SLATimerService


class TestSLATimerService:
    """Test suite for SLATimerService."""

    def test_start_timer_records_deadline(self) -> None:
        """Test 15: SLATimerService.start_timer() stores a deadline locally."""
        timer = SLATimerService()
        declared_at = datetime.now(timezone.utc)

        task_id = timer.start_timer("EM-abc123", declared_at, sla_seconds=900)

        assert task_id == "local-EM-abc123"
        assert "EM-abc123" in timer._deadlines

    def test_start_timer_without_celery(self) -> None:
        """start_timer works without Celery (testing mode)."""
        timer = SLATimerService()
        declared_at = datetime.now(timezone.utc)

        task_id = timer.start_timer("EM-abc123", declared_at, sla_seconds=900)

        assert task_id is not None
        assert "EM-abc123" in timer._deadlines

    def test_check_deadline_returns_true_when_breached(self) -> None:
        """Test 16: SLATimerService.check_deadline() returns True if deadline passed."""
        timer = SLATimerService()
        # Set deadline 1 second in the past
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        timer._deadlines["EM-abc123"] = past

        assert timer.check_deadline("EM-abc123") is True

    def test_check_deadline_returns_false_when_not_breached(self) -> None:
        """check_deadline returns False if deadline not yet passed."""
        timer = SLATimerService()
        # Set deadline 15 minutes in the future
        future = datetime.now(timezone.utc) + timedelta(minutes=15)
        timer._deadlines["EM-abc123"] = future

        assert timer.check_deadline("EM-abc123") is False

    def test_cancel_timer_removes_deadline(self) -> None:
        """cancel_timer removes the deadline tracking."""
        timer = SLATimerService()
        declared_at = datetime.now(timezone.utc)
        timer.start_timer("EM-abc123", declared_at)

        timer.cancel_timer("EM-abc123")

        assert "EM-abc123" not in timer._deadlines

    def test_check_deadline_returns_false_for_unknown_manifest(self) -> None:
        """check_deadline for a manifest that was never timer-started returns False."""
        timer = SLATimerService()
        assert timer.check_deadline("EM-never-started") is False
