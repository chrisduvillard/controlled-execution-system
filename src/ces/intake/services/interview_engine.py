"""Intake interview engine with session state machine and vault pre-check.

Implements INTAKE-01 through INTAKE-04:
- INTAKE-01: Phase-appropriate questions asked one at a time
- INTAKE-02: Three stages: mandatory, conditional, completeness
- INTAKE-03: Vault pre-check skips questions with verified answers
- INTAKE-04: Session persistence and reconstruction across interruptions

The IntakeSessionStateMachine follows the python-statemachine v3 pattern
from WorkflowEngine (D-11), using start_value for state reconstruction.

Exports:
    IntakeSessionStateMachine: State machine for interview stages.
    IntakeInterviewEngine: Async service for running intake interviews.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import yaml
from statemachine import State, StateMachine

from ces.control.models.intake import IntakeAnswer, IntakeQuestion
from ces.shared.enums import ActorType, AssumptionCategory, EventType

if TYPE_CHECKING:
    from ces.intake.protocols import AuditLedgerProtocol, VaultPreCheckProtocol


# ---------------------------------------------------------------------------
# Default questions path
# ---------------------------------------------------------------------------

_DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "questions" / "phase_questions.yaml"


# ---------------------------------------------------------------------------
# IntakeSessionStateMachine -- stage progression state machine
# ---------------------------------------------------------------------------


class IntakeSessionStateMachine(StateMachine):
    """State machine for intake interview stage progression.

    States: mandatory (initial) -> conditional -> completeness -> completed (final).

    Supports skip_conditional transition for phases with no conditional questions.
    Reconstruction from persisted state via start_value parameter (D-11 pattern).
    """

    # States
    mandatory = State(initial=True)
    conditional = State()
    completeness = State()
    completed = State(final=True)

    # Transitions
    advance_to_conditional = mandatory.to(conditional)
    advance_to_completeness = conditional.to(completeness)
    finish = completeness.to(completed)
    skip_conditional = mandatory.to(completeness)

    def __init__(self, start_value: str | None = None) -> None:
        """Initialize state machine, optionally reconstructing from persisted state.

        Args:
            start_value: State ID to reconstruct from (e.g., "conditional").
                         None starts from initial state (mandatory).
        """
        if start_value is not None:
            super().__init__(start_value=start_value)
        else:
            super().__init__()


# ---------------------------------------------------------------------------
# IntakeInterviewEngine -- async service
# ---------------------------------------------------------------------------


class IntakeInterviewEngine:
    """Orchestrates intake interviews with vault pre-check and audit logging.

    Runs phase-appropriate questions one at a time through three stages:
    mandatory, conditional, completeness. Integrates with:
    - IntakeRepository for session persistence
    - VaultPreCheckProtocol for auto-answering from knowledge vault
    - AuditLedgerProtocol for governance event logging

    Sessions persist across interruptions via DB reconstruction using
    the start_value parameter on IntakeSessionStateMachine.
    """

    def __init__(
        self,
        repository: object | None = None,
        vault_precheck: VaultPreCheckProtocol | None = None,
        audit_ledger: AuditLedgerProtocol | None = None,
        questions_path: Path | None = None,
    ) -> None:
        """Initialize the interview engine.

        Args:
            repository: IntakeRepository for session persistence (optional for testing).
            vault_precheck: VaultPreCheckProtocol for pre-checking answers in vault.
            audit_ledger: AuditLedgerProtocol for logging governance events.
            questions_path: Path to phase_questions.yaml. Defaults to bundled file.
        """
        self._repository = repository
        self._vault_precheck = vault_precheck
        self._audit = audit_ledger
        self._questions_path = questions_path or _DEFAULT_QUESTIONS_PATH

    # ---- Question loading ----

    def _load_questions(self, phase: int) -> dict[str, list[IntakeQuestion]]:
        """Load questions from YAML file and filter by phase.

        Args:
            phase: The phase number to load questions for.

        Returns:
            Dict mapping stage names to lists of IntakeQuestion objects.
            Keys: "mandatory", "conditional", "completeness".
        """
        with open(self._questions_path) as f:
            data = yaml.safe_load(f)

        result: dict[str, list[IntakeQuestion]] = {
            "mandatory": [],
            "conditional": [],
            "completeness": [],
        }

        phase_data = data.get("phases", {}).get(phase, {})
        for stage in ("mandatory", "conditional", "completeness"):
            raw_questions = phase_data.get(stage, [])
            for q in raw_questions:
                result[stage].append(
                    IntakeQuestion(
                        question_id=q["question_id"],
                        phase=phase,
                        stage=stage,
                        text=q["text"],
                        category=AssumptionCategory(q["category"]),
                        is_material=q.get("is_material", False),
                    )
                )

        return result

    # ---- Session lifecycle ----

    async def start_session(self, phase: int, project_id: str) -> str:
        """Create a new intake interview session.

        Creates an IntakeSessionStateMachine in mandatory state,
        persists to DB via repository, and logs to audit ledger.

        Args:
            phase: The phase number for this session.
            project_id: The project identifier.

        Returns:
            The session_id of the new session.
        """
        session_id = f"IS-{uuid.uuid4().hex[:12]}"

        if self._repository is not None:
            row = SimpleNamespace(
                session_id=session_id,
                phase=phase,
                current_stage="mandatory",
                project_id=project_id,
                answers={},
                assumptions={},
                blocked_questions=[],
            )
            await self._repository.save(row)  # type: ignore[attr-defined]

        if self._audit is not None:
            await self._audit.append_event(
                event_type=EventType.CLASSIFICATION,
                actor="intake_engine",
                actor_type=ActorType.CONTROL_PLANE,
                action_summary=f"Started intake session {session_id} for project {project_id}, phase {phase}",
            )

        return session_id

    async def _reconstruct_session(self, session_id: str) -> tuple[IntakeSessionStateMachine, object]:
        """Load session from DB and reconstruct state machine.

        Uses start_value parameter to restore the state machine
        to the persisted stage (D-11 pattern).

        Args:
            session_id: The session to reconstruct.

        Returns:
            Tuple of (state_machine, session_row).

        Raises:
            ValueError: If session not found in repository.
        """
        if self._repository is None:
            msg = "Repository required for session reconstruction"
            raise ValueError(msg)

        row = await self._repository.get_by_id(session_id)
        if row is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        sm = IntakeSessionStateMachine(start_value=row.current_stage)
        return sm, row

    async def get_next_question(self, session_id: str) -> IntakeQuestion | IntakeAnswer | None:
        """Get the next unanswered question for the current stage.

        Performs vault pre-check if available: when the vault has a verified
        answer, the question is auto-answered with source="knowledge_vault"
        and the engine moves to the next question.

        Args:
            session_id: The session to get the next question for.

        Returns:
            IntakeQuestion if a question needs human input,
            None if all questions in the current stage are answered.
        """
        sm, row = await self._reconstruct_session(session_id)
        questions = self._load_questions(row.phase)
        stage = row.current_stage

        if stage == "completed":
            return None

        stage_questions = questions.get(stage, [])
        answers = dict(row.answers) if row.answers else {}

        for question in stage_questions:
            if question.question_id in answers:
                continue

            # Vault pre-check: try to auto-answer from vault
            if self._vault_precheck is not None:
                vault_answer = await self._vault_precheck.find_verified_answer(
                    category=question.category.value,
                    question_text=question.text,
                )
                if vault_answer is not None:
                    # Auto-answer with vault source
                    auto_answer = IntakeAnswer(
                        answer_id=f"ANS-{uuid.uuid4().hex[:12]}",
                        question_id=question.question_id,
                        answer_text=vault_answer.content,
                        answered_by="knowledge_vault",
                        answered_at=datetime.now(timezone.utc),
                    )
                    answers[question.question_id] = auto_answer.model_dump(mode="json")
                    if self._repository is not None:
                        await self._repository.update_answers(session_id, answers)
                    continue

            # No vault answer -- return question for human
            return question

        # All questions in stage answered
        return None

    async def submit_answer(
        self,
        session_id: str,
        question_id: str,
        answer_text: str,
        answered_by: str,
    ) -> IntakeAnswer:
        """Record a human answer to an intake question.

        Creates an IntakeAnswer, records it in the session, persists
        via repository, and logs to audit ledger.

        Args:
            session_id: The session this answer belongs to.
            question_id: The question being answered.
            answer_text: The answer text.
            answered_by: Who provided the answer.

        Returns:
            The created IntakeAnswer.
        """
        answer = IntakeAnswer(
            answer_id=f"ANS-{uuid.uuid4().hex[:12]}",
            question_id=question_id,
            answer_text=answer_text,
            answered_by=answered_by,
            answered_at=datetime.now(timezone.utc),
        )

        if self._repository is not None:
            _, row = await self._reconstruct_session(session_id)
            answers = dict(row.answers) if row.answers else {}
            answers[question_id] = answer.model_dump(mode="json")
            await self._repository.update_answers(session_id, answers)

        if self._audit is not None:
            await self._audit.append_event(
                event_type=EventType.CLASSIFICATION,
                actor=answered_by,
                actor_type=ActorType.HUMAN,
                action_summary=f"Answered intake question {question_id} in session {session_id}",
            )

        return answer

    async def advance_stage(self, session_id: str) -> str:
        """Advance the session to the next interview stage.

        Determines the next stage based on current state and available
        conditional questions. If no conditional questions exist for the
        phase, skips directly from mandatory to completeness.

        Args:
            session_id: The session to advance.

        Returns:
            The name of the new stage.
        """
        sm, row = await self._reconstruct_session(session_id)
        questions = self._load_questions(row.phase)
        current = row.current_stage

        if current == "mandatory":
            conditional_questions = questions.get("conditional", [])
            if not conditional_questions:
                sm.skip_conditional()
                new_stage = "completeness"
            else:
                sm.advance_to_conditional()
                new_stage = "conditional"
        elif current == "conditional":
            sm.advance_to_completeness()
            new_stage = "completeness"
        elif current == "completeness":
            sm.finish()
            new_stage = "completed"
        else:
            msg = f"Cannot advance from stage: {current}"
            raise ValueError(msg)

        if self._repository is not None:
            await self._repository.update_stage(session_id, new_stage)

        return new_stage

    async def get_session_status(self, session_id: str) -> dict:
        """Get the current status of an intake session.

        Args:
            session_id: The session to check.

        Returns:
            Dict with current_stage, answered_count, total_questions,
            and blocked_questions.
        """
        _, row = await self._reconstruct_session(session_id)
        questions = self._load_questions(row.phase)
        answers = dict(row.answers) if row.answers else {}

        total = sum(len(qs) for qs in questions.values())
        answered = len(answers)

        return {
            "current_stage": row.current_stage,
            "answered_count": answered,
            "total_questions": total,
            "blocked_questions": list(row.blocked_questions) if row.blocked_questions else [],
        }
