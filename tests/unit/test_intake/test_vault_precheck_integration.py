"""Tests for intake engine vault pre-check integration with real KnowledgeVaultService.

Verifies that IntakeInterviewEngine works with KnowledgeVaultService as the
vault_precheck dependency (INTAKE-03). Tests use a KnowledgeVaultService with
a mock repository to simulate vault lookups without a database.

Tests:
- Vault has verified answer -> question auto-answered with "knowledge_vault"
- Vault has no answer -> question returned for human input
- Vault has stale-risk note -> question NOT auto-answered (only verified counts)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ces.control.models.intake import IntakeAnswer, IntakeQuestion
from ces.control.models.knowledge_vault import VaultNote
from ces.intake.services.interview_engine import IntakeInterviewEngine
from ces.knowledge.services.vault_service import KnowledgeVaultService
from ces.shared.enums import VaultCategory, VaultTrustLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_questions_path() -> Path:
    """Return path to the sample questions YAML."""
    return Path(__file__).resolve().parents[3] / "src" / "ces" / "intake" / "questions" / "phase_questions.yaml"


def _make_mock_intake_repository(
    session_data: dict | None = None,
) -> AsyncMock:
    """Create a mock IntakeRepository for the engine."""
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


def _make_mock_vault_repository(
    rows_by_category: dict[str, list] | None = None,
) -> MagicMock:
    """Create a mock VaultRepository that returns specified rows by category."""
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)

    async def _get_by_category(category: str) -> list:
        if rows_by_category:
            return rows_by_category.get(category, [])
        return []

    repo.get_by_category = AsyncMock(side_effect=_get_by_category)
    repo.get_by_trust_level = AsyncMock(return_value=[])
    repo.search_by_tags = AsyncMock(return_value=[])
    repo.update_trust_level = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=False)
    return repo


def _make_vault_note_row(
    *,
    note_id: str,
    category: str,
    trust_level: str,
    content: str,
    source: str = "test",
    tags: list | None = None,
    related_artifacts: list | None = None,
    invalidation_trigger: str | None = None,
) -> MagicMock:
    """Create a mock VaultNoteRow."""
    row = MagicMock()
    row.note_id = note_id
    row.category = category
    row.trust_level = trust_level
    row.content = content
    row.source = source
    row.tags = tags or []
    row.related_artifacts = related_artifacts or []
    row.invalidation_trigger = invalidation_trigger
    row.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVaultPreCheckIntegration:
    """Tests for intake engine vault pre-check with real KnowledgeVaultService."""

    async def test_vault_precheck_auto_answers_known_question(self) -> None:
        """Vault has verified answer -> question auto-answered with 'knowledge_vault'."""
        # Load the first mandatory question text so we can create a matching vault note
        engine_temp = IntakeInterviewEngine(
            questions_path=_sample_questions_path(),
        )
        questions = engine_temp._load_questions(phase=1)
        first_question = questions["mandatory"][0]

        # The intake engine passes question.category.value (e.g. "block") as
        # the category string to find_verified_answer. The vault service then
        # calls repository.get_by_category with that string. The mock row
        # must have a valid VaultCategory for _row_to_note conversion, but
        # the repository mock indexes by the assumption category key.
        vault_row = _make_vault_note_row(
            note_id="VN-precheck01",
            category="domain",  # Valid VaultCategory for _row_to_note
            trust_level="verified",
            # Content with high word overlap with the question text
            content=first_question.text,
        )
        vault_repo = _make_mock_vault_repository(
            # Indexed by the assumption category value ("block") which is what
            # IntakeInterviewEngine passes to find_verified_answer
            rows_by_category={first_question.category.value: [vault_row]},
        )

        # Create KnowledgeVaultService as vault_precheck
        vault_service = KnowledgeVaultService(
            repository=vault_repo,
            query_filter=lambda notes: notes,  # No filter for test
        )

        # Create IntakeInterviewEngine with vault service as precheck
        intake_repo = _make_mock_intake_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "mandatory",
                "answers": {},
            }
        )
        engine = IntakeInterviewEngine(
            repository=intake_repo,
            vault_precheck=vault_service,
            questions_path=_sample_questions_path(),
        )

        # get_next_question should auto-answer the first question via vault
        result = await engine.get_next_question("s1")

        # The first question was auto-answered, so we either get the second
        # question (if vault doesn't match it) or None (if all matched)
        # Verify the vault was called
        assert vault_repo.get_by_category.await_count >= 1

        # Verify the auto-answer was recorded in the repository
        assert intake_repo.update_answers.await_count >= 1

        # Check that the recorded answer has "knowledge_vault" as answered_by
        call_args = intake_repo.update_answers.call_args
        answers_dict = call_args[0][1]  # Second positional arg
        auto_answered = [
            v for v in answers_dict.values() if isinstance(v, dict) and v.get("answered_by") == "knowledge_vault"
        ]
        assert len(auto_answered) >= 1

    async def test_vault_precheck_passes_unknown_question(self) -> None:
        """Vault has no answer -> question returned for human input."""
        # Create vault with empty repository (no notes)
        vault_repo = _make_mock_vault_repository()
        vault_service = KnowledgeVaultService(
            repository=vault_repo,
            query_filter=lambda notes: notes,
        )

        intake_repo = _make_mock_intake_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "mandatory",
                "answers": {},
            }
        )
        engine = IntakeInterviewEngine(
            repository=intake_repo,
            vault_precheck=vault_service,
            questions_path=_sample_questions_path(),
        )

        result = await engine.get_next_question("s1")

        # No vault answers -> question returned for human
        assert isinstance(result, IntakeQuestion)
        assert result.stage == "mandatory"

    async def test_vault_precheck_ignores_stale_risk(self) -> None:
        """Vault has stale-risk note -> question NOT auto-answered (only verified)."""
        engine_temp = IntakeInterviewEngine(
            questions_path=_sample_questions_path(),
        )
        questions = engine_temp._load_questions(phase=1)
        first_question = questions["mandatory"][0]

        # Create vault with a stale-risk note (not verified)
        stale_row = _make_vault_note_row(
            note_id="VN-stale01",
            category="domain",  # Valid VaultCategory for _row_to_note
            trust_level="stale-risk",
            content=first_question.text,
        )
        vault_repo = _make_mock_vault_repository(
            rows_by_category={first_question.category.value: [stale_row]},
        )
        vault_service = KnowledgeVaultService(
            repository=vault_repo,
            query_filter=lambda notes: notes,
        )

        intake_repo = _make_mock_intake_repository(
            {
                "session_id": "s1",
                "phase": 1,
                "current_stage": "mandatory",
                "answers": {},
            }
        )
        engine = IntakeInterviewEngine(
            repository=intake_repo,
            vault_precheck=vault_service,
            questions_path=_sample_questions_path(),
        )

        result = await engine.get_next_question("s1")

        # Stale-risk note should NOT auto-answer -> question returned for human
        assert isinstance(result, IntakeQuestion)
        assert result.question_id == first_question.question_id
