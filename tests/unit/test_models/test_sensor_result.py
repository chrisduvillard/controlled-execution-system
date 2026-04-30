"""Tests for SensorResult and SensorPackResult frozen models (D-09)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.harness.models.sensor_result import SensorPackResult, SensorResult


class TestSensorResult:
    """SensorResult frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        sr = SensorResult(
            sensor_id="sec-001",
            sensor_pack="security",
            passed=True,
            score=0.95,
            details="All security checks passed",
            timestamp=datetime.now(timezone.utc),
        )
        assert sr.sensor_id == "sec-001"
        assert sr.passed is True
        assert sr.score == 0.95

    def test_frozen(self) -> None:
        sr = SensorResult(
            sensor_id="sec-001",
            sensor_pack="security",
            passed=True,
            score=0.95,
            details="OK",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(ValidationError):
            sr.passed = False  # type: ignore[misc]

    def test_score_must_be_between_0_and_1(self) -> None:
        """score must be 0.0 <= score <= 1.0."""
        with pytest.raises(ValidationError):
            SensorResult(
                sensor_id="x",
                sensor_pack="p",
                passed=True,
                score=1.5,
                details="invalid",
                timestamp=datetime.now(timezone.utc),
            )

    def test_score_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            SensorResult(
                sensor_id="x",
                sensor_pack="p",
                passed=False,
                score=-0.1,
                details="invalid",
                timestamp=datetime.now(timezone.utc),
            )


class TestSensorPackResult:
    """SensorPackResult frozen model tests."""

    def test_create_with_valid_data(self) -> None:
        now = datetime.now(timezone.utc)
        r1 = SensorResult(
            sensor_id="a",
            sensor_pack="pack1",
            passed=True,
            score=1.0,
            details="ok",
            timestamp=now,
        )
        r2 = SensorResult(
            sensor_id="b",
            sensor_pack="pack1",
            passed=False,
            score=0.3,
            details="fail",
            timestamp=now,
        )
        spr = SensorPackResult(
            pack_name="pack1",
            results=(r1, r2),
            pass_rate=0.5,
            all_passed=False,
        )
        assert spr.pack_name == "pack1"
        assert len(spr.results) == 2
        assert spr.pass_rate == 0.5
        assert spr.all_passed is False

    def test_frozen(self) -> None:
        now = datetime.now(timezone.utc)
        r1 = SensorResult(
            sensor_id="a",
            sensor_pack="pack1",
            passed=True,
            score=1.0,
            details="ok",
            timestamp=now,
        )
        spr = SensorPackResult(
            pack_name="pack1",
            results=(r1,),
            pass_rate=1.0,
            all_passed=True,
        )
        with pytest.raises(ValidationError):
            spr.pack_name = "other"  # type: ignore[misc]

    def test_all_passed_true_when_all_pass(self) -> None:
        now = datetime.now(timezone.utc)
        r1 = SensorResult(
            sensor_id="a",
            sensor_pack="p",
            passed=True,
            score=1.0,
            details="ok",
            timestamp=now,
        )
        r2 = SensorResult(
            sensor_id="b",
            sensor_pack="p",
            passed=True,
            score=0.9,
            details="ok",
            timestamp=now,
        )
        spr = SensorPackResult(
            pack_name="p",
            results=(r1, r2),
            pass_rate=1.0,
            all_passed=True,
        )
        assert spr.all_passed is True
