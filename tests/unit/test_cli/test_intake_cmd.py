"""Tests for ces intake command (intake_cmd module)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _get_app():
    """Import app lazily to avoid import errors during collection."""
    from ces.cli import app

    return app


def _make_question(question_id: str = "Q-001", text: str = "What is the scope?") -> Any:
    """Create a mock IntakeQuestion."""
    q = MagicMock()
    q.question_id = question_id
    q.text = text
    q.stage = "mandatory"
    q.category = "proceed"
    q.is_material = False
    return q


def _patch_services(mock_services: dict[str, Any]):
    """Return a patch that replaces get_services with a fake async context manager."""

    @asynccontextmanager
    async def _fake_get_services():
        yield mock_services

    return patch("ces.cli.intake_cmd.get_services", new=_fake_get_services)


class TestIntakeInterviewLoop:
    """Tests for ces intake interactive Q&A loop."""

    def test_intake_displays_questions(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces intake <phase> displays questions and accepts answers."""
        monkeypatch.chdir(ces_project)

        q1 = _make_question("Q-001", "What is the project scope?")
        q2 = _make_question("Q-002", "What are the constraints?")

        mock_engine = AsyncMock()
        mock_engine.start_session = AsyncMock(return_value="IS-abc123")
        # Return questions then None to end the loop
        mock_engine.get_next_question = AsyncMock(side_effect=[q1, q2, None, None])
        mock_engine.submit_answer = AsyncMock()
        mock_engine.advance_stage = AsyncMock(side_effect=["conditional", "completed"])
        mock_engine.get_session_status = AsyncMock(
            return_value={
                "current_stage": "completed",
                "answered_count": 2,
                "total_questions": 2,
                "blocked_questions": [],
            }
        )

        mock_services = {"intake_engine": mock_engine}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["intake", "1"], input="My scope\nNo constraints\n")

        assert result.exit_code == 0, f"stdout={result.stdout}"
        assert "scope" in result.stdout.lower() or "Q-001" in result.stdout

    def test_intake_json_output(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ces intake --json outputs session status as JSON."""
        monkeypatch.chdir(ces_project)

        mock_engine = AsyncMock()
        mock_engine.start_session = AsyncMock(return_value="IS-abc123")
        mock_engine.get_next_question = AsyncMock(return_value=None)
        mock_engine.advance_stage = AsyncMock(side_effect=["completed"])
        mock_engine.get_session_status = AsyncMock(
            return_value={
                "current_stage": "completed",
                "answered_count": 0,
                "total_questions": 0,
                "blocked_questions": [],
            }
        )

        mock_services = {"intake_engine": mock_engine}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["--json", "intake", "1"])

        assert result.exit_code == 0, f"stdout={result.stdout}"
        output = result.stdout.strip()
        data = json.loads(output)
        assert "current_stage" in data


class TestIntakeStageProgression:
    """Tests for intake stage progression."""

    def test_intake_advances_through_stages(self, ces_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Intake advances through mandatory -> conditional -> completeness -> completed."""
        monkeypatch.chdir(ces_project)

        mock_engine = AsyncMock()
        mock_engine.start_session = AsyncMock(return_value="IS-abc123")
        # mandatory has 1 question, then None -> advance; conditional returns None -> advance; completeness returns None -> finish
        q1 = _make_question("Q-001", "What is the scope?")
        mock_engine.get_next_question = AsyncMock(side_effect=[q1, None, None, None])
        mock_engine.submit_answer = AsyncMock()
        mock_engine.advance_stage = AsyncMock(side_effect=["conditional", "completeness", "completed"])
        mock_engine.get_session_status = AsyncMock(
            return_value={
                "current_stage": "completed",
                "answered_count": 1,
                "total_questions": 1,
                "blocked_questions": [],
            }
        )

        mock_services = {"intake_engine": mock_engine}

        with _patch_services(mock_services):
            app = _get_app()
            result = runner.invoke(app, ["intake", "1"], input="My answer\n")

        assert result.exit_code == 0, f"stdout={result.stdout}"
        # advance_stage should have been called
        assert mock_engine.advance_stage.call_count >= 1
