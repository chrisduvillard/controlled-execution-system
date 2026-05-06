"""Cross-service integration tests for Phase 5 subsystems.

Wires multiple services together (no DB, using mocked repositories)
to verify end-to-end integration:
- Intake engine -> vault service pre-check flow
- Brownfield register -> review -> promote to PRL lifecycle
- Emergency declare -> kill switch -> resolve lifecycle
- Vault note ranker -> guide pack tier limits
- LLM-05 compliance: no LLM imports in Phase 5 modules
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration

from ces.control.models.intake import IntakeQuestion
from ces.control.models.knowledge_vault import VaultNote
from ces.control.models.manifest import TaskManifest
from ces.intake.services.interview_engine import IntakeInterviewEngine
from ces.knowledge.services.note_ranker import NoteRanker
from ces.knowledge.services.vault_service import KnowledgeVaultService
from ces.shared.enums import (
    RiskTier,
    VaultCategory,
    VaultTrustLevel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_questions_path() -> Path:
    """Return path to the sample questions YAML."""
    return Path(__file__).resolve().parents[2] / "src" / "ces" / "intake" / "questions" / "phase_questions.yaml"


def _make_mock_intake_repository(
    session_data: dict | None = None,
) -> AsyncMock:
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


def _make_mock_vault_repository(
    rows_by_category: dict[str, list] | None = None,
) -> MagicMock:
    """Create a mock VaultRepository."""
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
    category: str = "patterns",
    trust_level: str = "agent-inferred",
    content: str = "Test content",
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


def _make_vault_note(
    *,
    note_id: str,
    category: VaultCategory = VaultCategory.PATTERNS,
    trust_level: VaultTrustLevel = VaultTrustLevel.AGENT_INFERRED,
    content: str = "Test content",
    source: str = "test",
    tags: list[str] | None = None,
) -> VaultNote:
    """Create a VaultNote domain model directly."""
    now = datetime.now(timezone.utc)
    return VaultNote(
        note_id=note_id,
        category=category,
        trust_level=trust_level,
        content=content,
        source=source,
        created_at=now,
        updated_at=now,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# Test 1: Intake -> Vault pre-check flow
# ---------------------------------------------------------------------------


class TestIntakeToVaultFlow:
    """Verify intake engine vault pre-check works with real vault service."""

    async def test_intake_to_vault_flow(self) -> None:
        """Create KnowledgeVaultService, add verified note. Create IntakeInterviewEngine
        with vault service as precheck. Start session, verify vault pre-check skips
        known questions."""
        # Load questions to get the first mandatory question
        engine_temp = IntakeInterviewEngine(
            questions_path=_sample_questions_path(),
        )
        questions = engine_temp._load_questions(phase=1)
        first_question = questions["mandatory"][0]

        # Create vault with a verified note matching the first question.
        # The row's category must be a valid VaultCategory for _row_to_note,
        # but the repository mock indexes by the assumption category key.
        vault_row = _make_vault_note_row(
            note_id="VN-int001",
            category="domain",  # Valid VaultCategory for _row_to_note
            trust_level="verified",
            content=first_question.text,
        )
        vault_repo = _make_mock_vault_repository(
            rows_by_category={first_question.category.value: [vault_row]},
        )
        vault_service = KnowledgeVaultService(
            repository=vault_repo,
            query_filter=lambda notes: notes,
        )

        # Wire intake engine with vault service as pre-check
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

        # Get next question -- first question should be auto-answered
        result = await engine.get_next_question("s1")

        # Vault was queried
        assert vault_repo.get_by_category.await_count >= 1

        # Auto-answer was stored
        assert intake_repo.update_answers.await_count >= 1

        # Check auto-answer has knowledge_vault source
        call_args = intake_repo.update_answers.call_args
        answers_dict = call_args[0][1]
        vault_answers = [
            v for v in answers_dict.values() if isinstance(v, dict) and v.get("answered_by") == "knowledge_vault"
        ]
        assert len(vault_answers) >= 1


# ---------------------------------------------------------------------------
# Test 2: Brownfield promote creates valid PRL
# ---------------------------------------------------------------------------


class TestBrownfieldPromoteCreatesPRL:
    """Verify brownfield register -> review -> promote lifecycle."""

    async def test_brownfield_promote_creates_valid_prl(self) -> None:
        """Create LegacyBehaviorService. Register behavior. Review it. Promote to PRL.
        Verify PRLItem has correct fields and register entry has back-reference."""
        from ces.brownfield.services.legacy_register import LegacyBehaviorService
        from ces.control.models.prl_item import PRLItem
        from ces.shared.enums import LegacyDisposition

        # Create mock repository
        repo = AsyncMock()
        audit = MagicMock()
        audit.append_event = AsyncMock()

        # Simulate save: store the row and return it
        saved_rows: dict[str, MagicMock] = {}

        async def _save(row: object) -> object:
            entry_id = getattr(row, "entry_id", None)
            if entry_id:
                saved_rows[entry_id] = row
            return row

        repo.save = AsyncMock(side_effect=_save)

        # register_behavior -> creates a new row
        service = LegacyBehaviorService(repository=repo, audit_ledger=audit)

        # We need to intercept the save to capture the entry_id
        behavior = await service.register_behavior(
            system="legacy-payments",
            behavior_description="Payment timeout after 30s causes auto-retry up to 3 times",
            inferred_by="agent-builder-1",
            confidence=0.85,
        )

        assert behavior.entry_id.startswith("OLB-")
        assert behavior.system == "legacy-payments"
        assert behavior.confidence == 0.85

        # Simulate review: get_by_id returns the row, update_disposition returns updated row
        review_row = MagicMock()
        review_row.entry_id = behavior.entry_id
        review_row.system = "legacy-payments"
        review_row.behavior_description = "Payment timeout after 30s causes auto-retry up to 3 times"
        review_row.inferred_by = "agent-builder-1"
        review_row.inferred_at = behavior.inferred_at
        review_row.confidence = 0.85
        review_row.disposition = None
        review_row.reviewed_by = None
        review_row.reviewed_at = None
        review_row.promoted_to_prl_id = None
        review_row.discarded = False
        repo.get_by_id = AsyncMock(return_value=review_row)

        # After review, return updated row with disposition
        reviewed_row = MagicMock()
        reviewed_row.entry_id = behavior.entry_id
        reviewed_row.system = "legacy-payments"
        reviewed_row.behavior_description = "Payment timeout after 30s causes auto-retry up to 3 times"
        reviewed_row.inferred_by = "agent-builder-1"
        reviewed_row.inferred_at = behavior.inferred_at
        reviewed_row.confidence = 0.85
        reviewed_row.disposition = "preserve"
        reviewed_row.reviewed_by = "human-reviewer"
        reviewed_row.reviewed_at = datetime.now(timezone.utc)
        reviewed_row.promoted_to_prl_id = None
        reviewed_row.discarded = False
        repo.update_disposition = AsyncMock(return_value=reviewed_row)

        reviewed = await service.review_behavior(
            entry_id=behavior.entry_id,
            disposition=LegacyDisposition.PRESERVE,
            reviewed_by="human-reviewer",
        )
        assert reviewed.disposition == LegacyDisposition.PRESERVE

        # Simulate promote: get_by_id returns reviewed row
        repo.get_by_id = AsyncMock(return_value=reviewed_row)

        # mark_promoted returns row with back-reference
        promoted_row = MagicMock()
        promoted_row.entry_id = behavior.entry_id
        promoted_row.system = "legacy-payments"
        promoted_row.behavior_description = "Payment timeout after 30s causes auto-retry up to 3 times"
        promoted_row.inferred_by = "agent-builder-1"
        promoted_row.inferred_at = behavior.inferred_at
        promoted_row.confidence = 0.85
        promoted_row.disposition = "preserve"
        promoted_row.reviewed_by = "human-reviewer"
        promoted_row.reviewed_at = reviewed.reviewed_at
        promoted_row.promoted_to_prl_id = None  # Will be set dynamically
        promoted_row.discarded = False

        async def _mark_promoted(eid: str, prl_id: str) -> MagicMock:
            promoted_row.promoted_to_prl_id = prl_id
            return promoted_row

        repo.mark_promoted = AsyncMock(side_effect=_mark_promoted)

        updated_entry, prl_item = await service.promote_to_prl(
            entry_id=behavior.entry_id,
            approver="human-approver",
        )

        # Verify PRLItem has correct fields
        assert isinstance(prl_item, PRLItem)
        assert prl_item.prl_id.startswith("PRL-")
        assert prl_item.statement == "Payment timeout after 30s causes auto-retry up to 3 times"
        assert prl_item.legacy_source_system == "legacy-payments"
        assert prl_item.owner == "human-approver"

        # Verify register entry has back-reference
        assert updated_entry.promoted_to_prl_id == prl_item.prl_id


# ---------------------------------------------------------------------------
# Test 3: Emergency full lifecycle
# ---------------------------------------------------------------------------


class TestEmergencyFullLifecycle:
    """Verify emergency declare -> kill switch -> resolve lifecycle."""

    async def test_emergency_full_lifecycle(self) -> None:
        """Create mock kill switch and audit ledger. Create EmergencyService.
        Declare emergency. Verify kill switch activated. Resolve emergency.
        Verify kill switch recovered and compensating controls logged."""
        from ces.control.models.kill_switch_state import ActivityClass
        from ces.emergency.services.emergency_service import EmergencyService

        # Mock kill switch
        kill_switch = MagicMock()
        kill_switch.activate = AsyncMock()
        kill_switch.recover = AsyncMock()

        # Mock audit ledger
        audit = MagicMock()
        audit.append_event = AsyncMock()

        service = EmergencyService(
            kill_switch=kill_switch,
            audit_ledger=audit,
        )

        # Declare emergency
        manifest = await service.declare_emergency(
            description="Critical payment bug",
            affected_files=("src/payments/processor.py",),
            declared_by="ops-lead",
        )

        assert isinstance(manifest, TaskManifest)
        assert manifest.manifest_id.startswith("EM-")
        assert "[EMERGENCY]" in manifest.description
        assert service.is_emergency_active()

        # Kill switch was activated
        kill_switch.activate.assert_awaited_once()
        activate_kwargs = kill_switch.activate.call_args
        assert activate_kwargs[1]["activity_class"] == ActivityClass.TASK_ISSUANCE

        # Audit ledger was called for declaration
        assert audit.append_event.await_count >= 1

        # Resolve emergency
        await service.resolve_emergency(
            manifest_id=manifest.manifest_id,
            resolved_by="ops-lead",
        )

        # Kill switch was recovered
        kill_switch.recover.assert_awaited_once()

        # Audit ledger was called for resolution + compensating controls
        # At minimum: declaration + resolution + post-incident review + retroactive evidence
        assert audit.append_event.await_count >= 4

        # Emergency is no longer active
        assert not service.is_emergency_active()


# ---------------------------------------------------------------------------
# Test 4: Vault note ranker with guide pack tier limits
# ---------------------------------------------------------------------------


class TestVaultNoteRankerTierLimits:
    """Verify NoteRanker.select_for_tier respects tier limits."""

    def test_vault_note_ranker_with_guide_pack_limits(self) -> None:
        """Create VaultNotes with different trust levels and tags.
        Call NoteRanker.select_for_tier for each tier.
        Verify limits: Tier A=3, B=5, C=10."""
        # Create 15 vault notes with verified trust
        notes = [
            _make_vault_note(
                note_id=f"VN-rank{i:03d}",
                trust_level=VaultTrustLevel.VERIFIED,
                content=f"Note {i} about API patterns",
                tags=("api", "patterns"),
            )
            for i in range(15)
        ]

        relevance_tags = ["api", "patterns"]

        # Tier A: max 3
        tier_a_notes = NoteRanker.select_for_tier(
            notes,
            RiskTier.A,
            relevance_tags,
        )
        assert len(tier_a_notes) == 3

        # Tier B: max 5
        tier_b_notes = NoteRanker.select_for_tier(
            notes,
            RiskTier.B,
            relevance_tags,
        )
        assert len(tier_b_notes) == 5

        # Tier C: max 10
        tier_c_notes = NoteRanker.select_for_tier(
            notes,
            RiskTier.C,
            relevance_tags,
        )
        assert len(tier_c_notes) == 10

    def test_ranker_excludes_stale_risk(self) -> None:
        """Stale-risk notes should be excluded from all tiers."""
        notes = [
            _make_vault_note(
                note_id="VN-stale01",
                trust_level=VaultTrustLevel.STALE_RISK,
                content="Stale note",
                tags=("api",),
            ),
            _make_vault_note(
                note_id="VN-verified01",
                trust_level=VaultTrustLevel.VERIFIED,
                content="Verified note",
                tags=("api",),
            ),
        ]

        result = NoteRanker.select_for_tier(notes, RiskTier.C, ["api"])
        assert len(result) == 1
        assert result[0].note_id == "VN-verified01"


# ---------------------------------------------------------------------------
# Test 5: No LLM imports in Phase 5 modules
# ---------------------------------------------------------------------------

# Prohibited LLM modules
PROHIBITED_MODULES = frozenset(
    {
        "anthropic",
        "openai",
        "litellm",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langchain_openai",
        "langchain_anthropic",
    }
)

# Phase 5 directories that must be free of LLM imports
PHASE5_DIRS = [
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "intake",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "knowledge",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "brownfield",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "emergency",
]


def _collect_phase5_python_files() -> list[pathlib.Path]:
    """Collect all .py files under Phase 5 directories."""
    files: list[pathlib.Path] = []
    for directory in PHASE5_DIRS:
        if directory.is_dir():
            files.extend(directory.rglob("*.py"))
    return sorted(files)


def _extract_imports(filepath: pathlib.Path) -> list[tuple[str, int]]:
    """Parse a Python file and extract all imported module names with line numbers."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                imports.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                root = node.module.split(".")[0]
                imports.append((root, node.lineno))
    return imports


class TestNoLLMImportsInPhase5:
    """LLM-05 compliance: Phase 5 modules must not import LLM libraries."""

    def test_phase5_dirs_exist(self) -> None:
        """Sanity check: Phase 5 directories must exist."""
        for directory in PHASE5_DIRS:
            assert directory.is_dir(), f"Expected directory not found: {directory}"

    def test_phase5_python_files_found(self) -> None:
        """Sanity check: there should be Python files to scan."""
        files = _collect_phase5_python_files()
        assert len(files) > 0, "No Python files found in Phase 5 directories"

    def test_no_llm_imports_in_phase5(self) -> None:
        """Every .py file in Phase 5 modules must be free of LLM imports."""
        violations: list[str] = []
        src_root = pathlib.Path(__file__).resolve().parents[2] / "src"

        for filepath in _collect_phase5_python_files():
            for module_root, lineno in _extract_imports(filepath):
                if module_root in PROHIBITED_MODULES:
                    relative = filepath.relative_to(src_root)
                    violations.append(f"  {relative}:{lineno} imports '{module_root}'")

        assert violations == [], (
            f"LLM-05 violation: found {len(violations)} prohibited LLM import(s) "
            f"in Phase 5 modules:\n" + "\n".join(violations)
        )
