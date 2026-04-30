"""Tests for ces gate command (gate_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.shared.enums import (
    BehaviorConfidence,
    GateType,
    RiskTier,
    TrustStatus,
)

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_gate_result(
    *,
    gate_type: GateType = GateType.HYBRID,
    base_gate_type: GateType = GateType.HYBRID,
    confidence_used: float = 0.95,
    phase: int = 3,
    risk_tier: RiskTier = RiskTier.B,
    behavior_confidence: BehaviorConfidence = BehaviorConfidence.BC1,
    trust_status: TrustStatus = TrustStatus.CANDIDATE,
    meta_review_selected: bool = False,
    hidden_check: bool = False,
) -> Any:
    """Create a GateEvaluationResult."""
    from ces.control.models.gate_result import GateEvaluationResult

    return GateEvaluationResult(
        gate_type=gate_type,
        base_gate_type=base_gate_type,
        confidence_used=confidence_used,
        phase=phase,
        risk_tier=risk_tier,
        behavior_confidence=behavior_confidence,
        trust_status=trust_status,
        meta_review_selected=meta_review_selected,
        hidden_check=hidden_check,
    )


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.gate_cmd.get_services", new=_fake_get_services)


class TestGateEvaluation:
    """Tests for ces gate with different configurations."""

    def test_gate_shows_gate_type_and_result(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces gate <phase> <scope> displays gate type and evaluation result."""
        monkeypatch.chdir(ces_project)
        gate_result = _make_gate_result(gate_type=GateType.HYBRID)

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = gate_result

        mock_services = {"gate_evaluator": mock_evaluator}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["gate", "3", "checkout"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "hybrid" in result.stdout.lower() or "HYBRID" in result.stdout

    def test_gate_with_risk_tier_option(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces gate with --risk-tier A shows HUMAN gate type."""
        monkeypatch.chdir(ces_project)
        gate_result = _make_gate_result(
            gate_type=GateType.HUMAN,
            risk_tier=RiskTier.A,
        )

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = gate_result

        mock_services = {"gate_evaluator": mock_evaluator}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["gate", "3", "checkout", "--risk-tier", "A"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "human" in result.stdout.lower() or "HUMAN" in result.stdout

    def test_gate_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces gate --json outputs gate result as JSON."""
        monkeypatch.chdir(ces_project)
        gate_result = _make_gate_result(gate_type=GateType.AGENT)

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = gate_result

        mock_services = {"gate_evaluator": mock_evaluator}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "gate", "3", "checkout"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        output = result.stdout.strip()
        # Should be parseable JSON
        data = json.loads(output)
        assert "gate_type" in data


class TestGateMetaReview:
    """Tests for meta-review and hidden check display."""

    def test_gate_shows_meta_review_indicator(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gate result with meta_review_selected=True shows indicator."""
        monkeypatch.chdir(ces_project)
        gate_result = _make_gate_result(meta_review_selected=True)

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = gate_result

        mock_services = {"gate_evaluator": mock_evaluator}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["gate", "3", "checkout"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # Should mention meta-review somewhere
        assert "meta" in result.stdout.lower() or "review" in result.stdout.lower()
