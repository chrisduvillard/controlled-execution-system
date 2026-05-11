"""Tests for post-success state protection sensor."""

from __future__ import annotations

import hashlib

import pytest

from ces.harness.sensors.post_success_state import PostSuccessStateSensor, protected_file_snapshot


@pytest.mark.asyncio
async def test_post_success_sensor_passes_when_protected_file_is_unchanged(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)

    result = await PostSuccessStateSensor().run(
        {"project_root": str(tmp_path), "post_success_protected_files": [snapshot]}
    )

    assert result.passed is True
    assert result.score == 1.0
    assert not result.findings


@pytest.mark.asyncio
async def test_post_success_sensor_blocks_deleted_protected_file(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)
    protected.unlink()

    result = await PostSuccessStateSensor().run(
        {"project_root": str(tmp_path), "post_success_protected_files": [snapshot]}
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.findings[0].category == "post_success_state_drift"
    assert result.findings[0].severity == "critical"
    assert "deleted" in result.findings[0].message


@pytest.mark.asyncio
async def test_post_success_sensor_blocks_modified_protected_file(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)
    protected.write_text("mutated evidence\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {"project_root": str(tmp_path), "post_success_protected_files": [snapshot]}
    )

    assert result.passed is False
    assert result.findings[0].location == "report.json"
    assert "modified after successful verification" in result.findings[0].message


@pytest.mark.asyncio
async def test_post_success_override_requires_revalidation(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)
    protected.write_text("intentional replacement\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [snapshot],
            "post_success_state_override": True,
            "post_success_revalidated": False,
        }
    )

    assert result.passed is False
    assert result.findings[0].category == "override_requires_revalidation"
    assert "Re-run validation" in result.findings[0].suggestion


@pytest.mark.asyncio
async def test_post_success_override_passes_after_revalidation(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)
    protected.write_text("intentional replacement\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [snapshot],
            "post_success_state_override": True,
            "post_success_revalidated": True,
        }
    )

    assert result.passed is True
    assert result.findings[0].category == "post_success_state_override"
    assert result.findings[0].severity == "medium"


@pytest.mark.asyncio
async def test_invalid_snapshot_cannot_be_overridden(tmp_path):
    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [{"path": "../outside.txt", "sha256": "a" * 64}],
            "post_success_state_override": True,
            "post_success_revalidated": True,
        }
    )

    assert result.passed is False
    assert result.findings[0].category == "invalid_snapshot"
    assert "escapes the project root" in result.findings[0].message


@pytest.mark.asyncio
async def test_absolute_snapshot_path_is_invalid(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [{"path": str(protected), "sha256": "a" * 64}],
            "post_success_state_override": True,
            "post_success_revalidated": True,
        }
    )

    assert result.passed is False
    assert result.findings[0].category == "invalid_snapshot"
    assert "project-relative" in result.findings[0].message


@pytest.mark.asyncio
async def test_non_boolean_override_does_not_pass(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")
    snapshot = protected_file_snapshot(tmp_path, protected)
    protected.write_text("mutated evidence\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [snapshot],
            "post_success_state_override": "true",
            "post_success_revalidated": "true",
        }
    )

    assert result.passed is False
    assert result.findings[0].category == "post_success_state_drift"


@pytest.mark.asyncio
async def test_malformed_sha_snapshot_cannot_be_overridden(tmp_path):
    protected = tmp_path / "report.json"
    protected.write_text("green evidence\n", encoding="utf-8")

    result = await PostSuccessStateSensor().run(
        {
            "project_root": str(tmp_path),
            "post_success_protected_files": [{"path": "report.json", "sha256": "not-a-sha"}],
            "post_success_state_override": True,
            "post_success_revalidated": True,
        }
    )

    assert result.passed is False
    assert result.findings[0].category == "invalid_snapshot"
    assert "not a valid SHA-256" in result.findings[0].message


def test_protected_file_snapshot_uses_relative_path_and_sha256(tmp_path):
    protected = tmp_path / "nested" / "report.json"
    protected.parent.mkdir()
    protected.write_text("green evidence\n", encoding="utf-8")

    snapshot = protected_file_snapshot(tmp_path, protected)

    assert snapshot == {
        "path": "nested/report.json",
        "sha256": hashlib.sha256(b"green evidence\n").hexdigest(),
    }
