"""Tests for ces classify command (classify_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_oracle_result(
    *,
    confidence: float = 0.95,
    action: str = "auto_accept",
    risk_tier: RiskTier = RiskTier.C,
    behavior_confidence: BehaviorConfidence = BehaviorConfidence.BC1,
    change_class: ChangeClass = ChangeClass.CLASS_1,
) -> Any:
    """Create a mock OracleClassificationResult."""
    from ces.control.models.oracle_result import OracleClassificationResult
    from ces.control.services.classification import ClassificationRule

    rule = ClassificationRule(
        description="Test rule",
        risk_tier=risk_tier,
        behavior_confidence=behavior_confidence,
        change_class=change_class,
    )

    return OracleClassificationResult(
        matched_rule=rule,
        confidence=confidence,
        top_matches=[(rule, confidence)],
        action=action,
    )


def _make_mock_manifest(
    manifest_id: str = "M-abc123def456",
    description: str = "Add shopping cart checkout flow",
) -> MagicMock:
    """Create a mock TaskManifest for lookup."""
    manifest = MagicMock()
    manifest.manifest_id = manifest_id
    manifest.description = description
    manifest.risk_tier = RiskTier.C
    manifest.behavior_confidence = BehaviorConfidence.BC1
    manifest.change_class = ChangeClass.CLASS_1
    return manifest


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.classify_cmd.get_services", new=_fake_get_services)


def _patch_services_error(error: Exception):
    """Return a patch that makes get_services raise an error."""

    @asynccontextmanager
    async def _fake_get_services():
        raise error
        yield  # pragma: no cover

    return patch("ces.cli.classify_cmd.get_services", new=_fake_get_services)


class TestClassifyValidManifest:
    """Tests for ces classify with a valid manifest ID."""

    def test_classify_shows_table_with_confidence(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces classify <id> displays classification result with confidence."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result(confidence=0.95)
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["classify", "M-abc123def456"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should display confidence info
        assert "95%" in result.stdout or "0.95" in result.stdout


class TestClassifyJsonOutput:
    """Tests for ces classify --json output mode."""

    def test_json_output_contains_classification(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces classify --json outputs JSON with classification fields."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result(confidence=0.85, action="human_review")
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "classify", "M-abc123def456"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Parse JSON output
        output = result.stdout.strip()
        decoder = json.JSONDecoder()
        idx = 0
        parsed_objects: list[dict[str, Any]] = []
        while idx < len(output):
            try:
                obj, end = decoder.raw_decode(output, idx)
                parsed_objects.append(obj)
                idx = end
            except json.JSONDecodeError:
                idx += 1
        assert parsed_objects, f"No JSON found in: {output}"
        # Should have classification fields
        data = parsed_objects[0]
        assert "confidence" in data or "risk_tier" in data


class TestClassifyInvalidManifest:
    """Tests for ces classify with an invalid manifest ID."""

    def test_invalid_manifest_shows_error(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces classify with unknown manifest-id shows error and exits non-zero."""
        monkeypatch.chdir(ces_project)

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=None)

        mock_oracle = MagicMock()

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["classify", "M-nonexistent"])

        assert result.exit_code != 0, f"stdout={result.stdout}"


class TestClassifyConfidenceColors:
    """Tests for confidence threshold color coding."""

    def test_high_confidence_display(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confidence >90% is displayed (green in Rich, value in JSON)."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result(confidence=0.95, action="auto_accept")
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["classify", "M-abc123def456"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "95%" in result.stdout

    def test_medium_confidence_display(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confidence 70-90% is displayed (yellow in Rich, value in JSON)."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result(confidence=0.82, action="human_review")
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["classify", "M-abc123def456"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "82%" in result.stdout

    def test_low_confidence_display(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Confidence <70% is displayed (red in Rich, value in JSON)."""
        monkeypatch.chdir(ces_project)
        oracle_result = _make_oracle_result(confidence=0.45, action="human_classify")
        mock_manifest = _make_mock_manifest()

        mock_oracle = MagicMock()
        mock_oracle.classify.return_value = oracle_result

        mock_manager = AsyncMock()
        mock_manager.get_manifest = AsyncMock(return_value=mock_manifest)

        mock_services = {
            "classification_oracle": mock_oracle,
            "manifest_manager": mock_manager,
        }

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["classify", "M-abc123def456"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "45%" in result.stdout


class TestClassifyMissingProject:
    """Tests for ces classify when not in a CES project."""

    def test_missing_project_root_exits_with_error(self, non_ces_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces classify outside a CES project exits with non-zero code."""
        monkeypatch.chdir(non_ces_dir)
        app = _get_app()
        result = runner.invoke(app, ["classify", "M-anything"])
        assert result.exit_code != 0
