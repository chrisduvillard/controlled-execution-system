"""Tests for local-mode persistence helpers."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from ces.brownfield.services.legacy_register import LegacyBehaviorService
from ces.local_store import LocalLegacyBehaviorRepository, LocalProjectStore
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    LegacyDisposition,
    RiskTier,
    WorkflowState,
)


class TestLocalBuilderBriefs:
    def test_builder_brief_round_trip(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")

        brief_id = store.save_builder_brief(
            request="Build an issue triage dashboard",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint", "Keep setup local-first"],
            acceptance_criteria=["Can create and list issues"],
            must_not_break=["CLI startup"],
            open_questions={
                "constraints": "Expose an HTTP endpoint",
                "acceptance": "Can create and list issues",
            },
            source_of_truth="README and tests",
            critical_flows=["Create issue", "Resolve issue"],
        )

        latest = store.get_latest_builder_brief()

        assert latest is not None
        assert latest.brief_id == brief_id
        assert latest.request == "Build an issue triage dashboard"
        assert latest.project_mode == "greenfield"
        assert latest.constraints == ["Expose an HTTP endpoint", "Keep setup local-first"]
        assert latest.acceptance_criteria == ["Can create and list issues"]
        assert latest.must_not_break == ["CLI startup"]
        assert latest.open_questions["constraints"] == "Expose an HTTP endpoint"
        assert latest.source_of_truth == "README and tests"
        assert latest.critical_flows == ["Create issue", "Resolve issue"]

    def test_latest_builder_brief_is_project_scoped(self, tmp_path: Path) -> None:
        db_path = tmp_path / ".ces" / "state.db"
        store_a = LocalProjectStore(db_path, project_id="proj-a")
        store_b = LocalProjectStore(db_path, project_id="proj-b")

        brief_a = store_a.save_builder_brief(
            request="Project A request",
            project_mode="greenfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=[],
            open_questions={},
        )
        store_b.save_builder_brief(
            request="Project B request",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=[],
            open_questions={},
        )

        latest_a = store_a.get_latest_builder_brief()

        assert latest_a is not None
        assert latest_a.brief_id == brief_a
        assert latest_a.request == "Project A request"
        store_a.close()
        store_b.close()


class TestLocalBuilderSessions:
    def test_builder_session_round_trip(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")

        brief_id = store.save_builder_brief(
            request="Build an issue triage dashboard",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint"],
            acceptance_criteria=["Can create and list issues"],
            must_not_break=["CLI startup"],
            open_questions={"constraints": "Expose an HTTP endpoint"},
        )
        session_id = store.save_builder_session(
            brief_id=brief_id,
            request="Build an issue triage dashboard",
            project_mode="greenfield",
            stage="ready_to_run",
            next_action="run_continue",
            last_action="brief_captured",
            attempt_count=1,
            brownfield_review_state={
                "group_index": 1,
                "item_index": 0,
                "group_defaults": {"must_not_break": "preserve"},
            },
        )

        latest = store.get_latest_builder_session()

        assert latest is not None
        assert latest.session_id == session_id
        assert latest.brief_id == brief_id
        assert latest.stage == "ready_to_run"
        assert latest.next_action == "run_continue"
        assert latest.last_action == "brief_captured"
        assert latest.attempt_count == 1
        assert latest.brownfield_review_state == {
            "group_index": 1,
            "item_index": 0,
            "group_defaults": {"must_not_break": "preserve"},
        }

    def test_latest_builder_session_is_project_scoped(self, tmp_path: Path) -> None:
        db_path = tmp_path / ".ces" / "state.db"
        store_a = LocalProjectStore(db_path, project_id="proj-a")
        store_b = LocalProjectStore(db_path, project_id="proj-b")

        session_a = store_a.save_builder_session(
            brief_id=None,
            request="Project A session",
            project_mode="greenfield",
            stage="ready_to_run",
            next_action="run_continue",
            last_action="brief_captured",
        )
        store_b.save_builder_session(
            brief_id=None,
            request="Project B session",
            project_mode="brownfield",
            stage="blocked",
            next_action="review_brownfield",
            last_action="brownfield_review_in_progress",
        )

        latest_a = store_a.get_latest_builder_session()

        assert latest_a is not None
        assert latest_a.session_id == session_a
        assert latest_a.request == "Project A session"
        store_a.close()
        store_b.close()

    def test_latest_builder_session_can_be_synthesized_from_latest_brief(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")

        brief_id = store.save_builder_brief(
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            open_questions={"must_not_break": "CSV export format"},
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
        )

        session = store.ensure_latest_builder_session()

        assert session is not None
        assert session.brief_id == brief_id
        assert session.request == "Modernize billing exports"
        assert session.project_mode == "brownfield"
        assert session.stage == "awaiting_review"
        assert session.next_action == "review_evidence"
        assert session.manifest_id == "M-123"
        assert session.evidence_packet_id == "EP-123"

    def test_latest_builder_session_snapshot_resolves_complete_chain(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")
        brief_id = store.save_builder_brief(
            request="Modernize billing exports",
            project_mode="brownfield",
            constraints=["Keep CSV compatibility"],
            acceptance_criteria=["Exports include invoice notes"],
            must_not_break=["CSV export format"],
            open_questions={"must_not_break": "CSV export format"},
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            manifest_id="M-123",
            evidence_packet_id="EP-123",
        )

        now = datetime.now(timezone.utc)
        manifest = SimpleNamespace(
            manifest_id="M-123",
            description="Modernize billing exports",
            risk_tier=RiskTier.B,
            behavior_confidence=BehaviorConfidence.BC2,
            change_class=ChangeClass.CLASS_2,
            status=ArtifactStatus.DRAFT,
            workflow_state=WorkflowState.IN_FLIGHT,
            content_hash=None,
            expires_at=now + timedelta(hours=1),
            created_at=now,
            model_dump=lambda mode="json": {
                "manifest_id": "M-123",
                "description": "Modernize billing exports",
            },
        )
        store.save_manifest(manifest)
        store.save_runtime_execution(
            "M-123",
            {
                "runtime_name": "codex",
                "runtime_version": "1.0.0",
                "reported_model": "gpt-5.4",
                "invocation_ref": "run-123",
                "exit_code": 0,
                "stdout": "Done",
                "stderr": "",
                "duration_seconds": 0.5,
                "transcript_path": None,
            },
        )
        store.save_evidence(
            "M-123",
            packet_id="EP-123",
            summary="Evidence is ready",
            challenge="Check the CSV snapshots",
            triage_color="yellow",
            content={"execution": {"exit_code": 0}},
        )
        store.save_approval(
            "M-123",
            decision="approve",
            rationale="Looks good",
        )
        store.save_builder_session(
            brief_id=brief_id,
            request="Modernize billing exports",
            project_mode="brownfield",
            stage="completed",
            next_action="start_new_session",
            last_action="approval_recorded",
            manifest_id="M-123",
            runtime_manifest_id="M-123",
            evidence_packet_id="EP-123",
            approval_manifest_id="M-123",
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export"],
            brownfield_review_state={"groups": [], "group_index": 0, "item_index": 0},
            brownfield_entry_ids=["OLB-1", "OLB-2"],
            brownfield_reviewed_count=2,
            brownfield_remaining_count=0,
        )

        snapshot = store.get_latest_builder_session_snapshot()

        assert snapshot is not None
        assert snapshot.request == "Modernize billing exports"
        assert snapshot.latest_artifact == "approval"
        assert snapshot.is_chain_complete is True
        assert snapshot.runtime_execution is not None
        assert snapshot.runtime_execution.exit_code == 0
        assert snapshot.evidence is not None
        assert snapshot.evidence["packet_id"] == "EP-123"
        assert snapshot.approval is not None
        assert snapshot.approval.decision == "approve"
        assert snapshot.brownfield is not None
        assert snapshot.brownfield.entry_ids == ["OLB-1", "OLB-2"]
        assert snapshot.brownfield.reviewed_count == 2
        assert snapshot.brownfield.remaining_count == 0

    def test_latest_builder_session_snapshot_degrades_for_partial_chain(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")
        store.save_builder_brief(
            request="Build a habit tracker",
            project_mode="greenfield",
            constraints=["Expose an HTTP endpoint"],
            acceptance_criteria=["Users can create habits"],
            must_not_break=["CLI startup"],
            open_questions={"constraints": "Expose an HTTP endpoint"},
        )

        snapshot = store.get_latest_builder_session_snapshot()

        assert snapshot is not None
        assert snapshot.request == "Build a habit tracker"
        assert snapshot.project_mode == "greenfield"
        assert snapshot.manifest is None
        assert snapshot.runtime_execution is None
        assert snapshot.evidence is None
        assert snapshot.approval is None
        assert snapshot.latest_artifact == "brief"
        assert snapshot.is_chain_complete is False
        assert snapshot.brownfield is None


class TestLocalProjectStoreHardening:
    """0.1.2 security polish: file perms + stdout/stderr secret scrubbing."""

    def test_state_db_and_parent_have_tight_permissions(self, tmp_path: Path) -> None:
        import os
        import stat
        import sys

        if sys.platform == "win32":
            pytest.skip("POSIX permission bits")

        from ces.local_store import LocalProjectStore

        db_path = tmp_path / ".ces" / "state.db"
        LocalProjectStore(db_path=db_path, project_id="probe")
        parent_mode = stat.S_IMODE(os.stat(db_path.parent).st_mode)
        db_mode = stat.S_IMODE(os.stat(db_path).st_mode)
        assert parent_mode == 0o700, f".ces/ is 0o{parent_mode:o}, expected 0o700"
        assert db_mode == 0o600, f"state.db is 0o{db_mode:o}, expected 0o600"

    def test_save_runtime_execution_scrubs_stdout_stderr(self, tmp_path: Path) -> None:
        from types import SimpleNamespace

        from ces.local_store import LocalProjectStore

        store = LocalProjectStore(db_path=tmp_path / "state.db", project_id="probe")
        now = datetime.now(timezone.utc)
        manifest = SimpleNamespace(
            manifest_id="M-scrub",
            description="Probe scrubbing",
            risk_tier=RiskTier.C,
            behavior_confidence=BehaviorConfidence.BC1,
            change_class=ChangeClass.CLASS_3,
            status=ArtifactStatus.DRAFT,
            workflow_state=WorkflowState.IN_FLIGHT,
            content_hash=None,
            expires_at=now + timedelta(hours=1),
            created_at=now,
            model_dump=lambda mode="json": {"manifest_id": "M-scrub"},
        )
        store.save_manifest(manifest)
        store.save_runtime_execution(
            "M-scrub",
            {
                "runtime_name": "codex",
                "runtime_version": "1.0.0",
                "reported_model": None,
                "invocation_ref": "inv-1",
                "exit_code": 0,
                "stdout": "Loaded ANTHROPIC_API_KEY=" + "sk" + "-" + "ant" + "-" + "fixture from .env",
                "stderr": "AWS_SECRET_ACCESS_KEY=" + "A" + "KIA" + "SYNTHETIC" + "EXAMPLE visible",
                "duration_seconds": 0.1,
                "transcript_path": None,
            },
        )
        record = store.get_runtime_execution("M-scrub")
        assert record is not None
        assert "sk-ant-leak-12345" not in record.stdout
        assert "SYNTHETIC" + "EXAMPLE" not in record.stderr
        assert "<REDACTED>" in record.stdout or "<REDACTED>" in record.stderr


class TestLocalLegacyBehaviorRepository:
    @pytest.mark.asyncio
    async def test_local_legacy_behaviors_round_trip_through_service(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj-local")
        repository = LocalLegacyBehaviorRepository(store)
        service = LegacyBehaviorService(repository=repository)

        entry = await service.register_behavior(
            system="legacy-billing",
            behavior_description="Invoices above $1000 receive a 5% discount",
            inferred_by="builder-flow",
            confidence=0.8,
            source_manifest_id="M-123",
        )

        pending = await service.get_pending_behaviors()
        assert [item.entry_id for item in pending] == [entry.entry_id]

        reviewed = await service.review_behavior(
            entry_id=entry.entry_id,
            disposition=LegacyDisposition.PRESERVE,
            reviewed_by="cli-user",
        )

        assert reviewed.disposition == LegacyDisposition.PRESERVE
        assert reviewed.reviewed_by == "cli-user"
        assert await service.get_pending_behaviors() == []

        by_system = await service.get_behaviors_by_system("legacy-billing")
        assert len(by_system) == 1
        assert by_system[0].entry_id == entry.entry_id
        assert by_system[0].disposition == LegacyDisposition.PRESERVE


class TestReviewFindingsSyntheticPrimaryKey:
    """review_findings should use a synthetic INTEGER PK, not promote finding_id.

    finding_id is a free-form label the reviewer attaches; promoting it to PRIMARY
    KEY (in any form — global or composite with manifest_id) created collision
    paths whenever reviewers hard-coded duplicate IDs. The synthetic PK frees
    finding_id to be whatever the reviewer wants, and a non-unique index on
    manifest_id keeps `get_review_findings` lookups fast.
    """

    @staticmethod
    def _make_finding(*, finding_id: str, title: str, role: str = "structural") -> object:
        from ces.harness.models.review_assignment import ReviewerRole
        from ces.harness.models.review_finding import ReviewFinding, ReviewFindingSeverity

        return ReviewFinding(
            finding_id=finding_id,
            reviewer_role=ReviewerRole(role),
            severity=ReviewFindingSeverity.HIGH,
            category="test",
            file_path="src/x.py",
            line_number=1,
            title=title,
            description="d",
            recommendation="r",
            confidence=0.9,
        )

    @classmethod
    def _make_aggregated(cls, *, findings: list[object]) -> object:
        from ces.harness.models.review_assignment import ReviewAssignment, ReviewerRole
        from ces.harness.models.review_finding import ReviewResult
        from ces.harness.services.findings_aggregator import AggregatedReview

        assignment = ReviewAssignment(role=ReviewerRole.STRUCTURAL, model_id="m", agent_id="a")
        result = ReviewResult(
            assignment=assignment,
            findings=tuple(findings),
            summary="",
            review_duration_seconds=0.0,
        )
        return AggregatedReview(
            review_results=(result,),
            all_findings=tuple(findings),
            critical_count=0,
            high_count=len(findings),
        )

    def test_new_db_uses_synthetic_integer_primary_key(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
        with store._connect() as conn:
            cols = conn.execute("PRAGMA table_info(review_findings)").fetchall()
            indexes = conn.execute("PRAGMA index_list(review_findings)").fetchall()

        pk_cols = {row["name"] for row in cols if row["pk"] > 0}
        assert pk_cols == {"id"}, f"expected synthetic 'id' PK, got {pk_cols}"
        # Index on manifest_id keeps get_review_findings WHERE manifest_id=? fast
        assert any(idx["name"] == "idx_review_findings_manifest" for idx in indexes), "missing manifest_id index"

    def test_same_finding_id_can_appear_in_two_manifests(self, tmp_path: Path) -> None:
        """Cross-manifest collision (e.g. reviewer hard-codes 'F-001') no longer breaks persistence."""
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")

        agg_a = self._make_aggregated(findings=[self._make_finding(finding_id="F-001", title="A-finding")])
        agg_b = self._make_aggregated(findings=[self._make_finding(finding_id="F-001", title="B-finding")])

        store.save_review_findings("M-a", agg_a)
        store.save_review_findings("M-b", agg_b)

        assert store.get_review_findings("M-a")["findings"][0]["title"] == "A-finding"
        assert store.get_review_findings("M-b")["findings"][0]["title"] == "B-finding"

    def test_two_reviewers_same_finding_id_in_one_manifest(self, tmp_path: Path) -> None:
        """Within a single Tier A triad, two reviewers hard-coding the same ID must not collide.

        This was the gap in PR #4's earlier composite PK — `(manifest_id, finding_id)`
        prevented cross-manifest duplicates but still failed if the same triad's
        reviewers reused a label. The synthetic PK makes finding_id collisions
        within a manifest a non-issue.
        """
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")

        agg = self._make_aggregated(
            findings=[
                self._make_finding(finding_id="F-001", title="From semantic", role="semantic"),
                self._make_finding(finding_id="F-001", title="From red_team", role="red_team"),
            ]
        )
        store.save_review_findings("M-triad", agg)

        loaded = store.get_review_findings("M-triad")
        assert loaded is not None
        titles = {f["title"] for f in loaded["findings"]}
        assert titles == {"From semantic", "From red_team"}

    def test_resaving_same_manifest_replaces_findings(self, tmp_path: Path) -> None:
        """save_review_findings DELETE-then-INSERT semantics survive the schema change."""
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")

        agg_first = self._make_aggregated(findings=[self._make_finding(finding_id="F-001", title="first")])
        agg_second = self._make_aggregated(findings=[self._make_finding(finding_id="F-001", title="second")])

        store.save_review_findings("M-x", agg_first)
        store.save_review_findings("M-x", agg_second)

        loaded = store.get_review_findings("M-x")
        assert loaded is not None and len(loaded["findings"]) == 1
        assert loaded["findings"][0]["title"] == "second"

    def test_recovers_from_interrupted_migration_temp_only(self, tmp_path: Path) -> None:
        """Crash after DROP review_findings, before RENAME — temp table is the SoT.

        The next initialize() must complete the rename so user data is not silently
        abandoned by the next CREATE-IF-NOT-EXISTS pass.
        """
        import sqlite3

        db_path = tmp_path / ".ces" / "state.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(db_path)
        # Simulate interrupted migration: only review_findings_new exists
        conn.executescript(
            """
            CREATE TABLE review_findings_new (
                id INTEGER PRIMARY KEY,
                finding_id TEXT NOT NULL,
                manifest_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                file_path TEXT,
                line_number INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO review_findings_new (
                finding_id, manifest_id, project_id, reviewer_role,
                severity, category, file_path, line_number, title,
                description, recommendation, confidence, created_at
            ) VALUES (
                'F-rescued', 'M-rescued', 'proj', 'structural', 'high', 'test',
                'src/x.py', 1, 'Mid-migration data', 'd', 'r', 0.9, '2026-01-01T00:00:00Z'
            );
            """
        )
        conn.commit()
        conn.close()

        store = LocalProjectStore(db_path, project_id="proj")

        # The data should now live in review_findings (renamed from temp), not lost.
        # We query the table directly because get_review_findings requires a paired
        # review_aggregates row which an interrupted migration wouldn't have left.
        with store._connect() as conn:
            rescued = conn.execute("SELECT title FROM review_findings WHERE finding_id = 'F-rescued'").fetchone()
            temp_present = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings_new'"
            ).fetchone()
        assert rescued is not None and rescued["title"] == "Mid-migration data", (
            "data was abandoned by interrupted-migration recovery"
        )
        assert temp_present is None, "temp table not cleaned up after rename"

    def test_recovers_from_interrupted_migration_both_tables(self, tmp_path: Path) -> None:
        """Crash after CREATE NEW, before DROP — main table is still the SoT, drop the temp."""
        import sqlite3

        db_path = tmp_path / ".ces" / "state.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(db_path)
        # Both tables exist: original review_findings (with old data) + temp (mid-migration copy)
        conn.executescript(
            """
            CREATE TABLE review_findings (
                finding_id TEXT PRIMARY KEY,
                manifest_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                file_path TEXT,
                line_number INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            INSERT INTO review_findings VALUES (
                'F-original', 'M-original', 'proj', 'structural', 'high', 'test',
                'src/x.py', 1, 'Original data', 'd', 'r', 0.9, '2026-01-01T00:00:00Z'
            );
            CREATE TABLE review_findings_new (
                id INTEGER PRIMARY KEY,
                finding_id TEXT NOT NULL,
                manifest_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                file_path TEXT,
                line_number INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        store = LocalProjectStore(db_path, project_id="proj")

        # The temp should be dropped. The main table should then be migrated to synthetic PK
        # by the normal migration path (which still runs after recovery).
        with store._connect() as conn:
            temp_present = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='review_findings_new'"
            ).fetchone()
            cols = conn.execute("PRAGMA table_info(review_findings)").fetchall()
            preserved = conn.execute("SELECT title FROM review_findings WHERE finding_id = 'F-original'").fetchone()
        assert temp_present is None, "stranded temp table not cleaned up"
        pk_cols = {row["name"] for row in cols if row["pk"] > 0}
        assert pk_cols == {"id"}, "main table did not migrate to synthetic PK after recovery"
        assert preserved is not None and preserved["title"] == "Original data"

    @pytest.mark.parametrize(
        "legacy_create_sql",
        [
            # Original schema: global PK on finding_id alone
            """
            CREATE TABLE review_findings (
                finding_id TEXT PRIMARY KEY,
                manifest_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                file_path TEXT,
                line_number INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            # Intermediate schema (PR #4 first pass): composite (manifest_id, finding_id)
            """
            CREATE TABLE review_findings (
                finding_id TEXT NOT NULL,
                manifest_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL,
                file_path TEXT,
                line_number INTEGER,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (manifest_id, finding_id)
            )
            """,
        ],
        ids=["original_global_pk", "intermediate_composite_pk"],
    )
    def test_legacy_schemas_migrate_on_initialize(self, tmp_path: Path, legacy_create_sql: str) -> None:
        """Both legacy schema shapes migrate transparently to the synthetic-PK shape."""
        import sqlite3

        db_path = tmp_path / ".ces" / "state.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(db_path)
        conn.executescript(legacy_create_sql)
        conn.execute(
            """
            INSERT INTO review_findings (
                finding_id, manifest_id, project_id, reviewer_role,
                severity, category, file_path, line_number, title,
                description, recommendation, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "F-legacy",
                "M-old",
                "proj",
                "structural",
                "high",
                "test",
                "src/x.py",
                1,
                "Old finding",
                "d",
                "r",
                0.9,
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
        conn.close()

        # Initialize triggers the migration
        store = LocalProjectStore(db_path, project_id="proj")

        with store._connect() as conn:
            cols = conn.execute("PRAGMA table_info(review_findings)").fetchall()
            preserved = conn.execute("SELECT title FROM review_findings WHERE finding_id = 'F-legacy'").fetchone()

        pk_cols = {row["name"] for row in cols if row["pk"] > 0}
        assert pk_cols == {"id"}, "migration did not rebuild with synthetic PK"
        assert preserved is not None and preserved["title"] == "Old finding", "legacy data lost"


class TestLocalAuditRows:
    def test_promoted_prl_items_are_project_scoped(self, tmp_path: Path) -> None:
        db_path = tmp_path / ".ces" / "state.db"
        store_a = LocalProjectStore(db_path, project_id="proj-a")
        store_b = LocalProjectStore(db_path, project_id="proj-b")

        store_a.save_prl_item(
            SimpleNamespace(
                model_dump=lambda mode="json": {
                    "schema_type": "prl_item",
                    "prl_id": "PRL-a",
                    "statement": "Preserve legacy tax rounding",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            )
        )
        store_b.save_prl_item(
            SimpleNamespace(
                model_dump=lambda mode="json": {
                    "schema_type": "prl_item",
                    "prl_id": "PRL-b",
                    "statement": "Preserve legacy invoice numbering",
                    "created_at": "2026-01-02T00:00:00+00:00",
                }
            )
        )

        assert [item["prl_id"] for item in store_a.get_promoted_prl_items()] == ["PRL-a"]
        assert [item["prl_id"] for item in store_b.get_promoted_prl_items()] == ["PRL-b"]
        store_a.close()
        store_b.close()

    def test_duplicate_audit_entry_id_fails_instead_of_replacing_history(self, tmp_path: Path) -> None:
        store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
        row = SimpleNamespace(
            entry_id="AE-duplicate",
            timestamp=datetime.now(timezone.utc),
            event_type="state_transition",
            actor="tester",
            actor_type="human",
            action_summary="Initial event",
            decision="approved",
            rationale="test",
            scope={"manifest_id": "M-1"},
            metadata_extra=None,
            project_id="proj",
            prev_hash="GENESIS",
            entry_hash="hash-1",
        )

        store.append_audit_entry(row)

        with pytest.raises(sqlite3.IntegrityError):
            store.append_audit_entry(row)
        store.close()
