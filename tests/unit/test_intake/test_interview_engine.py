"""Tests for the intake interview engine and session state machine.

Tests cover:
- IntakeSessionStateMachine transitions: mandatory -> conditional -> completeness -> completed
- Skip transition: mandatory -> completeness (when no conditional questions)
- No backward transitions
- IntakeInterviewEngine session lifecycle: start, get_next_question, submit_answer, advance_stage
- Vault pre-check: auto-answer with vault source, pass-through when no answer
- Session reconstruction from DB state via start_value
- Questions loaded from YAML file and filtered by phase
- Audit ledger integration: start_session and submit_answer log events
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from statemachine.exceptions import TransitionNotAllowed

from ces.control.models.intake import IntakeAnswer, IntakeQuestion
from ces.control.models.knowledge_vault import VaultNote
from ces.intake.protocols import AuditLedgerProtocol, VaultPreCheckProtocol
from ces.intake.services.interview_engine import (
    IntakeInterviewEngine,
    IntakeSessionStateMachine,
)
from ces.shared.enums import AssumptionCategory, VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# IntakeSessionStateMachine -- direct state machine tests
# ---------------------------------------------------------------------------


class TestIntakeSessionStateMachine:
    """Test the intake session state machine transitions."""

    def test_initial_state_is_mandatory(self) -> None:
        """Test 1: IntakeSessionStateMachine starts in `mandatory` state."""
        sm = IntakeSessionStateMachine()
        state_ids = {s.id for s in sm.configuration}
        assert "mandatory" in state_ids

    def test_full_transition_sequence(self) -> None:
        """Test 2: Transitions: mandatory -> conditional -> completeness -> completed."""
        sm = IntakeSessionStateMachine()
        sm.advance_to_conditional()
        assert {s.id for s in sm.configuration} == {"conditional"}

        sm.advance_to_completeness()
        assert {s.id for s in sm.configuration} == {"completeness"}

        sm.finish()
        assert {s.id for s in sm.configuration} == {"completed"}

    def test_skip_conditional(self) -> None:
        """Test 3: Skip transition: mandatory -> completeness (when no conditional questions)."""
        sm = IntakeSessionStateMachine()
        sm.skip_conditional()
        assert {s.id for s in sm.configuration} == {"completeness"}

    def test_cannot_transition_backward(self) -> None:
        """Test 4: Cannot transition backward (completeness -> mandatory raises)."""
        sm = IntakeSessionStateMachine()
        sm.advance_to_conditional()
        sm.advance_to_completeness()
        # Attempting to go back to conditional or mandatory should raise
        with pytest.raises(TransitionNotAllowed):
            sm.advance_to_conditional()


# ---------------------------------------------------------------------------
# IntakeInterviewEngine -- service tests
# ---------------------------------------------------------------------------


def _make_mock_repository(session_data: dict | None = None) -> AsyncMock:
    """Create a mock IntakeRepository."""
    repo = AsyncMock()
    if session_data:
        row = MagicMock()
        row.session_id = session_data.get("session_id", "test-session-1")
        row.phase = session_data.get("phase", 1)
        row.current_stage = session_data.get("current_stage", "mandatory")
        row.project_id = session_data.get("project_id", "test-project")
        row.answers = session_data.get("answers", {})
        row.assumptions = session_data.get("assumptions", {})
        row.blocked_questions = session_data.get("blocked_questions", [])
        repo.get_by_id.return_value = row
    else:
        repo.get_by_id.return_value = None
    repo.save.return_value = MagicMock(session_id="test-session-1")
    repo.update_stage.return_value = MagicMock()
    repo.update_answers.return_value = MagicMock()
    return repo


def _sample_questions_path() -> Path:
    """Return path to the sample questions YAML."""
    return Path(__file__).resolve().parents[3] / "src" / "ces" / "intake" / "questions" / "phase_questions.yaml"


class TestIntakeInterviewEngineStartSession:
    """Test session creation."""

    async def test_start_session_creates_session(self) -> None:
        """Test 5: IntakeInterviewEngine.start_session() creates a new session with mandatory stage."""
        repo = _make_mock_repository()
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        session_id = await engine.start_session(phase=1, project_id="proj-1")
        assert session_id is not None
        assert isinstance(session_id, str)
        repo.save.assert_called_once()


class TestIntakeInterviewEngineGetNextQuestion:
    """Test question retrieval."""

    async def test_get_next_question_returns_question(self) -> None:
        """Test 6: IntakeInterviewEngine.get_next_question() returns questions for current stage."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        result = await engine.get_next_question("s1")
        assert result is not None
        assert isinstance(result, IntakeQuestion)
        assert result.stage == "mandatory"

    async def test_get_next_question_returns_none_when_exhausted(self) -> None:
        """Test 7: IntakeInterviewEngine.get_next_question() returns None when stage is exhausted."""
        # Pre-fill answers for all mandatory questions of phase 1
        repo = _make_mock_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "mandatory",
                "answers": {
                    "Q-P1-M01": "answer1",
                    "Q-P1-M02": "answer2",
                    "Q-P1-M03": "answer3",
                    "Q-P1-M04": "answer4",
                    "Q-P1-M05": "answer5",
                },
            }
        )
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        result = await engine.get_next_question("s1")
        assert result is None


class TestVaultPreCheck:
    """Test vault pre-check integration."""

    async def test_vault_precheck_auto_answers(self) -> None:
        """Test 8: Vault pre-check: when vault has verified answer, question is auto-answered with vault source."""
        from datetime import datetime, timezone

        vault_note = VaultNote(
            note_id="VN-1",
            category=VaultCategory.DOMAIN,
            trust_level=VaultTrustLevel.VERIFIED,
            content="Python with FastAPI",
            source="project-docs",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        vault_mock = AsyncMock(spec=VaultPreCheckProtocol)
        vault_mock.find_verified_answer.return_value = vault_note

        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            vault_precheck=vault_mock,
            questions_path=_sample_questions_path(),
        )
        # When vault returns an answer for every question, get_next_question
        # should keep auto-answering and eventually return None
        result = await engine.get_next_question("s1")
        # The vault was called at least once
        assert vault_mock.find_verified_answer.call_count >= 1
        # Auto-answered questions should be recorded in the repo
        assert repo.update_answers.call_count >= 1

    async def test_vault_precheck_passes_through_when_no_answer(self) -> None:
        """Test 9: Vault pre-check: when vault has no answer, question is returned for human."""
        vault_mock = AsyncMock(spec=VaultPreCheckProtocol)
        vault_mock.find_verified_answer.return_value = None

        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            vault_precheck=vault_mock,
            questions_path=_sample_questions_path(),
        )
        result = await engine.get_next_question("s1")
        assert isinstance(result, IntakeQuestion)
        vault_mock.find_verified_answer.assert_called_once()


class TestIntakeInterviewEngineSubmitAnswer:
    """Test answer submission."""

    async def test_submit_answer_records_answer(self) -> None:
        """Test 10: IntakeInterviewEngine.submit_answer() records answer and advances question pointer."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        answer = await engine.submit_answer(
            session_id="s1",
            question_id="Q-P1-M01",
            answer_text="Build a REST API",
            answered_by="human-user",
        )
        assert isinstance(answer, IntakeAnswer)
        assert answer.question_id == "Q-P1-M01"
        assert answer.answer_text == "Build a REST API"
        assert answer.answered_by == "human-user"
        repo.update_answers.assert_called_once()


class TestIntakeInterviewEngineAdvanceStage:
    """Test stage advancement."""

    async def test_advance_stage_transitions(self) -> None:
        """Test 11: IntakeInterviewEngine.advance_stage() transitions state machine to next stage."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        new_stage = await engine.advance_stage("s1")
        assert new_stage in ("conditional", "completeness")
        repo.update_stage.assert_called_once()


class TestSessionReconstruction:
    """Test session persistence and reconstruction."""

    async def test_session_reconstruction_from_db(self) -> None:
        """Test 12: Session reconstruction: engine can resume from DB state via start_value."""
        repo = _make_mock_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "conditional",
                "answers": {"Q-P1-M01": "answer1"},
            }
        )
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        # Reconstruct session -- should start in conditional state
        sm, row = await engine._reconstruct_session("s1")
        state_ids = {s.id for s in sm.configuration}
        assert "conditional" in state_ids


class TestQuestionsLoading:
    """Test YAML question loading."""

    async def test_questions_loaded_from_yaml(self) -> None:
        """Test 13: Questions loaded from YAML file and filtered by phase."""
        engine = IntakeInterviewEngine(
            questions_path=_sample_questions_path(),
        )
        questions = engine._load_questions(phase=1)
        assert "mandatory" in questions
        assert "conditional" in questions
        assert "completeness" in questions
        assert len(questions["mandatory"]) >= 3
        for q in questions["mandatory"]:
            assert isinstance(q, IntakeQuestion)
            assert q.phase == 1
            assert q.stage == "mandatory"


class TestAuditLedgerIntegration:
    """Test audit ledger logging."""

    async def test_audit_events_logged(self) -> None:
        """Test 14: Audit ledger integration: start_session and submit_answer log events when audit_ledger provided."""
        audit_mock = AsyncMock(spec=AuditLedgerProtocol)
        repo = _make_mock_repository()
        engine = IntakeInterviewEngine(
            repository=repo,
            audit_ledger=audit_mock,
            questions_path=_sample_questions_path(),
        )
        # start_session should log
        await engine.start_session(phase=1, project_id="proj-1")
        assert audit_mock.append_event.call_count >= 1

        # Reset and test submit_answer
        audit_mock.reset_mock()
        repo_with_session = _make_mock_repository(
            {"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}}
        )
        engine2 = IntakeInterviewEngine(
            repository=repo_with_session,
            audit_ledger=audit_mock,
            questions_path=_sample_questions_path(),
        )
        await engine2.submit_answer(
            session_id="s1",
            question_id="Q-P1-M01",
            answer_text="Some answer",
            answered_by="user",
        )
        assert audit_mock.append_event.call_count >= 1


class TestIntakeEngineEdgeCases:
    """Tests for edge cases and error paths to improve coverage."""

    async def test_start_session_without_repository(self) -> None:
        """start_session works without repository (no persistence)."""
        engine = IntakeInterviewEngine(
            repository=None,
            questions_path=_sample_questions_path(),
        )
        session_id = await engine.start_session(phase=1, project_id="proj-1")
        assert session_id.startswith("IS-")

    async def test_start_session_without_audit_ledger(self) -> None:
        """start_session works without audit ledger."""
        repo = _make_mock_repository()
        engine = IntakeInterviewEngine(
            repository=repo,
            audit_ledger=None,
            questions_path=_sample_questions_path(),
        )
        session_id = await engine.start_session(phase=1, project_id="proj-1")
        assert session_id.startswith("IS-")

    async def test_reconstruct_without_repository_raises(self) -> None:
        """_reconstruct_session raises ValueError without repository."""
        engine = IntakeInterviewEngine(
            repository=None,
            questions_path=_sample_questions_path(),
        )
        with pytest.raises(ValueError, match="Repository required"):
            await engine._reconstruct_session("nonexistent")

    async def test_reconstruct_session_not_found_raises(self) -> None:
        """_reconstruct_session raises ValueError if session not found."""
        repo = _make_mock_repository()  # get_by_id returns None
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        with pytest.raises(ValueError, match="Session not found"):
            await engine._reconstruct_session("nonexistent")

    async def test_get_next_question_completed_stage(self) -> None:
        """get_next_question returns None for completed stage."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "completed", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        result = await engine.get_next_question("s1")
        assert result is None

    async def test_advance_stage_from_conditional(self) -> None:
        """advance_stage transitions from conditional to completeness."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "conditional", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        new_stage = await engine.advance_stage("s1")
        assert new_stage == "completeness"

    async def test_advance_stage_from_completeness(self) -> None:
        """advance_stage transitions from completeness to completed."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "completeness", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        new_stage = await engine.advance_stage("s1")
        assert new_stage == "completed"

    async def test_advance_stage_from_completed_raises(self) -> None:
        """advance_stage from completed stage raises ValueError."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "completed", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        with pytest.raises(ValueError, match="Cannot advance"):
            await engine.advance_stage("s1")

    async def test_get_session_status(self) -> None:
        """get_session_status returns correct counts."""
        repo = _make_mock_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "mandatory",
                "answers": {"Q-P1-M01": "answer1"},
                "blocked_questions": ["Q-P1-M03"],
            }
        )
        engine = IntakeInterviewEngine(
            repository=repo,
            questions_path=_sample_questions_path(),
        )
        status = await engine.get_session_status("s1")
        assert status["current_stage"] == "mandatory"
        assert status["answered_count"] == 1
        assert status["total_questions"] > 0
        assert "Q-P1-M03" in status["blocked_questions"]

    async def test_submit_answer_without_repository(self) -> None:
        """submit_answer works without repository."""
        engine = IntakeInterviewEngine(
            repository=None,
            questions_path=_sample_questions_path(),
        )
        answer = await engine.submit_answer(
            session_id="s1",
            question_id="Q-P1-M01",
            answer_text="Test answer",
            answered_by="user",
        )
        assert answer.question_id == "Q-P1-M01"
        assert answer.answered_by == "user"

    async def test_submit_answer_without_audit(self) -> None:
        """submit_answer works without audit ledger."""
        repo = _make_mock_repository({"session_id": "s1", "phase": 1, "current_stage": "mandatory", "answers": {}})
        engine = IntakeInterviewEngine(
            repository=repo,
            audit_ledger=None,
            questions_path=_sample_questions_path(),
        )
        answer = await engine.submit_answer(
            session_id="s1",
            question_id="Q-P1-M01",
            answer_text="Test answer",
            answered_by="user",
        )
        assert answer.question_id == "Q-P1-M01"
