"""Semantic Review Layer PRD coverage tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ces.execution.processes import run_sync_command

runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    result = run_sync_command(["git", *args], cwd=repo, timeout_seconds=30)
    assert result.exit_code == 0, result.stderr
    return result.stdout


def _make_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".ces").mkdir()
    (repo / "src" / "ces" / "execution").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "src" / "ces" / "execution" / "runner.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    (repo / "tests" / "test_runner.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    (repo / "docs" / "usage.md").write_text("# Usage\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    (repo / "src" / "ces" / "execution" / "runner.py").write_text(
        "import subprocess\n\ndef run(path):\n    return subprocess.run(['python', path], check=False).returncode\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_runner.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    (repo / "docs" / "usage.md").write_text("# Usage\n\nUpdated.\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "semantic review fixture")


def _get_app():
    from ces.cli import app

    return app


def test_semantic_review_models_round_trip(tmp_path: Path) -> None:
    from ces.review.models import (
        AgentProvenance,
        DiffIndex,
        DiffStats,
        IntentCoverageMap,
        ReviewArtifactBundle,
        ReviewMetadata,
        ReviewPath,
        RiskMap,
        VerificationSummary,
    )

    metadata = ReviewMetadata(
        review_id="20260520-120000-abcdef12",
        created_at=datetime.now(timezone.utc),
        repo_root="project",
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="abcdef123456",
        artifact_paths={"review_brief": ".ces/reviews/20260520-120000-abcdef12/review-brief.md"},
    )
    bundle = ReviewArtifactBundle(
        metadata=metadata,
        root_path=tmp_path / ".ces" / "reviews" / metadata.review_id,
        review_brief_path=tmp_path / ".ces" / "reviews" / metadata.review_id / "review-brief.md",
        diff_index=DiffIndex(
            base_ref="HEAD~1",
            head_ref="HEAD",
            diff_fingerprint="abcdef123456",
            stats=DiffStats(files_changed=0, insertions=0, deletions=0),
        ),
        risk_map=RiskMap(),
        intent_coverage=IntentCoverageMap(objective="Ship review layer"),
        review_path=ReviewPath(),
        verification_summary=VerificationSummary(status="unknown"),
        agent_provenance=AgentProvenance(mode="local_diff_limited"),
    )

    loaded = ReviewArtifactBundle.model_validate_json(bundle.model_dump_json())

    assert loaded.schema_version == "1.0"
    assert loaded.metadata.review_id == metadata.review_id
    assert loaded.review_brief_path.name == "review-brief.md"


def test_artifact_store_rejects_symlinked_reviews_dir(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore
    from ces.review.models import ReviewMetadata

    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".ces").mkdir()
    (project / ".ces" / "reviews").symlink_to(outside, target_is_directory=True)
    metadata = ReviewMetadata(
        review_id="20260520-120000-abcdef12",
        created_at=datetime.now(timezone.utc),
        repo_root="project",
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="abcdef123456",
    )

    with pytest.raises(ValueError, match="symlink"):
        SemanticReviewArtifactStore(project).prepare_bundle_dir(metadata)

    assert list(outside.iterdir()) == []


def test_artifact_store_rejects_symlinked_artifact_file(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore
    from ces.review.models import (
        AgentProvenance,
        DiffIndex,
        DiffStats,
        IntentCoverageMap,
        ReviewArtifactBundle,
        ReviewMetadata,
        ReviewPath,
        RiskMap,
        VerificationSummary,
    )

    project = tmp_path / "project"
    project.mkdir()
    review_dir = project / ".ces" / "reviews" / "20260520-120000-abcdef12"
    review_dir.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (review_dir / "review-brief.md").symlink_to(outside)
    metadata = ReviewMetadata(
        review_id="20260520-120000-abcdef12",
        created_at=datetime.now(timezone.utc),
        repo_root="project",
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="abcdef123456",
    )
    bundle = ReviewArtifactBundle(
        metadata=metadata,
        root_path=review_dir,
        review_brief_path=review_dir / "review-brief.md",
        diff_index=DiffIndex(
            base_ref="HEAD~1",
            head_ref="HEAD",
            diff_fingerprint="abcdef123456",
            stats=DiffStats(files_changed=0, insertions=0, deletions=0),
        ),
        risk_map=RiskMap(),
        intent_coverage=IntentCoverageMap(objective="x"),
        review_path=ReviewPath(),
        verification_summary=VerificationSummary(status="unknown"),
        agent_provenance=AgentProvenance(mode="local_diff_limited"),
    )

    with pytest.raises(ValueError, match="symlink"):
        SemanticReviewArtifactStore(project).write_bundle(bundle, review_brief="# Review\n")

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_classifier_risk_and_intent_coverage_are_evidence_bounded() -> None:
    from ces.review.file_classifier import classify_path
    from ces.review.intent_coverage import build_intent_coverage_from_items
    from ces.review.models import ChangedFile, DiffIndex, DiffStats, VerificationSummary
    from ces.review.risk import build_risk_map

    classification = classify_path("src/ces/execution/runtimes/adapters.py")
    changed = ChangedFile(
        path="src/ces/execution/runtimes/adapters.py",
        status="modified",
        additions=10,
        deletions=1,
        classification=classification,
        content_excerpt="subprocess.run(['python'], check=False)",
    )
    diff_index = DiffIndex(
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="fp",
        stats=DiffStats(files_changed=1, insertions=10, deletions=1),
        changed_files=(changed,),
    )
    risk_map = build_risk_map(diff_index, VerificationSummary(status="not_run"))
    coverage = build_intent_coverage_from_items(
        objective="Export semantic review JSON",
        requirement_texts=("REQ-1: export semantic review JSON", "REQ-2: post to GitHub"),
        diff_index=diff_index,
        verification=VerificationSummary(status="not_run"),
        deferred_scope=("REQ-2",),
    )

    assert classification.conceptual_area == "execution"
    assert risk_map.review_first[0].path == "src/ces/execution/runtimes/adapters.py"
    assert any(signal.kind == "subprocess_execution" for signal in risk_map.review_first[0].signals)
    assert coverage.items[0].status in {"unknown", "partially_implemented"}
    assert coverage.items[1].status == "intentionally_deferred"


def test_renderer_and_github_comment_redact_secret_values(tmp_path: Path) -> None:
    from ces.review.github_comment import _public_path, render_github_comment
    from ces.review.renderer import render_review_brief
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Add key sk-test-secret-value to docs"),
    )

    markdown = render_review_brief(bundle)
    comment = render_github_comment(bundle)
    truncated_comment = render_github_comment(bundle, max_chars=120)

    for heading in [
        "# CES Review Brief:",
        "## Bottom Line",
        "## Objective",
        "## What Changed",
        "## Review This First",
        "## Architecture and Behavior Impact",
        "## Intent Coverage",
        "## Risk Map",
        "## Verification Evidence",
        "## Agent Provenance and Assumptions",
        "## Human Review Checklist",
        "## Not Changed / Deferred",
        "## Raw Artifact Links",
    ]:
        assert heading in markdown
    assert "sk-test-secret-value" not in markdown
    assert "sk-test-secret-value" not in comment.body
    assert "<REDACTED>" in markdown
    assert "Comment truncated by CES length cap" in truncated_comment.body
    assert _public_path(Path("review-brief.md")) == "review-brief.md"
    assert "<!-- ces-semantic-review:" in comment.body


def test_service_generate_writes_full_artifact_bundle_for_git_diff(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Add semantic review for execution changes"),
    )

    assert bundle.root_path.is_relative_to(tmp_path / ".ces" / "reviews")
    for artifact in [
        "metadata.json",
        "diff-index.json",
        "risk-map.json",
        "intent-coverage.json",
        "intent-coverage.md",
        "review-path.md",
        "agent-provenance.json",
        "verification-summary.json",
        "review-brief.md",
    ]:
        assert (bundle.root_path / artifact).is_file(), artifact
    paths = {file.path for file in bundle.diff_index.changed_files}
    assert "src/ces/execution/runner.py" in paths
    assert ".github/workflows/ci.yml" in paths
    assert bundle.risk_map.review_first[0].conceptual_area in {"execution", "ci", "packaging"}
    assert SemanticReviewArtifactStore(tmp_path).latest_bundle_metadata().review_id == bundle.metadata.review_id


def test_review_cli_generate_list_show_and_github_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = _get_app()

    generated = runner.invoke(
        app,
        [
            "review",
            "generate",
            "--base",
            "HEAD~1",
            "--head",
            "HEAD",
            "--objective",
            "Add semantic review CLI",
            "--json",
        ],
    )
    assert generated.exit_code == 0, generated.stdout
    payload = json.loads(generated.stdout)
    review_id = payload["review_id"]
    assert payload["artifact_dir"].endswith(review_id)

    listed = runner.invoke(app, ["review", "list", "--json"])
    assert listed.exit_code == 0, listed.stdout
    assert review_id in listed.stdout

    shown = runner.invoke(app, ["review", "show", "--section", "path"])
    assert shown.exit_code == 0, shown.stdout
    assert "Review Path" in shown.stdout

    comment = runner.invoke(app, ["review", "github-comment", "--dry-run", "--review-id", review_id])
    assert comment.exit_code == 0, comment.stdout
    assert "ces-semantic-review" in comment.stdout
    assert "Review first" in comment.stdout


def test_proof_card_references_latest_semantic_review(tmp_path: Path) -> None:
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService
    from ces.verification.proof_card import build_proof_card

    _make_repo(tmp_path)
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Add proof integration"),
    )

    proof = build_proof_card(tmp_path).to_dict()

    assert proof["semantic_review"]["review_id"] == bundle.metadata.review_id
    assert proof["semantic_review"]["review_brief"].endswith("review-brief.md")
    assert proof["semantic_review"]["risk_level"] in {"low", "medium", "high", "critical"}


def test_approval_warning_and_audit_refs_include_semantic_review(tmp_path: Path) -> None:
    from ces.cli.approve_cmd import _semantic_review_for_approval
    from ces.control.services.audit_ledger import AuditLedgerService
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Add approval integration"),
    )

    support = _semantic_review_for_approval(tmp_path)

    assert support.review_id == bundle.metadata.review_id
    assert support.evidence_refs == (f"semantic-review:{bundle.metadata.review_id}",)
    assert any("verification evidence" in warning for warning in support.warnings)

    async def record() -> tuple[str, ...]:
        ledger = AuditLedgerService(secret_key=b"semantic-review-test-key")
        entry = await ledger.record_approval(
            manifest_id="manifest-1",
            actor="human",
            decision="approved",
            rationale="reviewed semantic artifact",
            evidence_refs=list(support.evidence_refs),
        )
        return entry.evidence_refs

    import asyncio

    assert asyncio.run(record()) == (f"semantic-review:{bundle.metadata.review_id}",)


def test_review_default_rewrite_preserves_brownfield_review_subcommand() -> None:
    from ces.cli import _rewrite_review_default

    assert _rewrite_review_default(["review"]) == ["review", "run"]
    assert _rewrite_review_default(["review", "M-123"]) == ["review", "run", "M-123"]
    assert _rewrite_review_default(["review", "generate"]) == ["review", "generate"]
    assert _rewrite_review_default(["brownfield", "review", "OLB-123"]) == [
        "brownfield",
        "review",
        "OLB-123",
    ]


def test_stale_detection_catches_same_size_worktree_content_change(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    tracked = tmp_path / "docs" / "usage.md"
    tracked.write_text("alpha\n", encoding="utf-8")
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD",
        options=ReviewGenerationOptions(objective="Update docs content"),
    )

    tracked.write_text("omega\n", encoding="utf-8")

    assert SemanticReviewArtifactStore(tmp_path).is_stale(bundle.metadata) is True


def test_stale_detection_catches_verification_evidence_change(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    latest_verification = tmp_path / ".ces" / "latest-verification.json"
    latest_verification.write_text(
        json.dumps({"verification": {"passed": True, "commands": [{"command": "pytest", "exit_code": 0}]}}),
        encoding="utf-8",
    )
    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD",
        options=ReviewGenerationOptions(objective="Review verification evidence"),
    )

    assert bundle.verification_summary.status == "passed"

    latest_verification.write_text(
        json.dumps({"verification": {"passed": False, "commands": [{"command": "pytest", "exit_code": 1}]}}),
        encoding="utf-8",
    )

    assert SemanticReviewArtifactStore(tmp_path).is_stale(bundle.metadata) is True


def test_service_generate_from_subdirectory_writes_artifacts_at_git_root(tmp_path: Path) -> None:
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    bundle = SemanticReviewService().generate(
        tmp_path / "src",
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Review from nested cwd"),
    )

    assert bundle.root_path.is_relative_to(tmp_path / ".ces" / "reviews")
    assert not (tmp_path / "src" / ".ces" / "reviews").exists()


def test_committed_diff_review_uses_head_blob_not_dirty_worktree(tmp_path: Path) -> None:
    from ces.review.service import ReviewGenerationOptions, SemanticReviewService

    _make_repo(tmp_path)
    dirty_path = tmp_path / "src" / "ces" / "execution" / "runner.py"
    dirty_path.write_text("DIRTY_MARKER = True\n", encoding="utf-8")

    bundle = SemanticReviewService().generate(
        tmp_path,
        base_ref="HEAD~1",
        head_ref="HEAD",
        options=ReviewGenerationOptions(objective="Review committed diff only"),
    )

    runner_file = next(file for file in bundle.diff_index.changed_files if file.path.endswith("runner.py"))
    assert "DIRTY_MARKER" not in runner_file.content_excerpt
    assert "subprocess.run" in runner_file.content_excerpt


def test_artifact_store_rejects_metadata_review_id_mismatch(tmp_path: Path) -> None:
    from ces.review.artifacts import SemanticReviewArtifactStore

    project = tmp_path / "project"
    review_dir = project / ".ces" / "reviews" / "20260520-120000-abcdef12"
    review_dir.mkdir(parents=True)
    (review_dir / "metadata.json").write_text(
        json.dumps(
            {
                "review_id": "20260520-120000-badbadbad",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "repo_root": "project",
                "base_ref": "HEAD~1",
                "head_ref": "HEAD",
                "diff_fingerprint": "abcdef123456",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match"):
        SemanticReviewArtifactStore(project).load_bundle("20260520-120000-abcdef12")


def test_github_comment_update_targets_existing_semantic_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ces.review.github_comment as github_comment_module
    from ces.execution.processes import ProcessResult
    from ces.review.github_comment import post_github_comment
    from ces.review.models import GithubReviewComment

    calls: list[tuple[tuple[str, ...], Path | None]] = []

    def fake_run(command, **kwargs):
        command_tuple = tuple(str(part) for part in command)
        calls.append((command_tuple, kwargs.get("cwd")))
        if command_tuple == ("gh", "api", "user", "--jq", ".login"):
            return ProcessResult(command=command_tuple, exit_code=0, stdout="vega\n", stderr="")
        if command_tuple[:2] == ("gh", "api") and "issues/42/comments" in command_tuple[2]:
            return ProcessResult(command=command_tuple, exit_code=0, stdout="123\n", stderr="")
        return ProcessResult(command=command_tuple, exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(github_comment_module, "run_sync_command", fake_run)
    comment = GithubReviewComment(
        review_id="review-1",
        body="<!-- ces-semantic-review:fingerprint=abc;review_id=review-1 -->\nbody",
        update_marker="<!-- ces-semantic-review:fingerprint=abc;review_id=review-1 -->",
    )

    repo_root = (tmp_path / "review-repo").resolve()
    post_github_comment(comment, pr=42, repo_root=repo_root, update_existing=True)

    commands = [command for command, _cwd in calls]
    assert any(command[:3] == ("gh", "api", "repos/:owner/:repo/issues/comments/123") for command in commands)
    assert not any("--edit-last" in command for command in commands)
    assert all(cwd == repo_root for _command, cwd in calls)
    lookup_call = next(command for command in commands if "issues/42/comments" in command[2])
    assert comment.update_marker in lookup_call[-1]
    assert "vega" in lookup_call[-1]


def test_semantic_project_root_fails_closed_on_symlinked_ces(tmp_path: Path) -> None:
    import typer

    from ces.cli.review_cmd import _resolve_semantic_project_root

    project = tmp_path / "project"
    external_state = tmp_path / "external-state"
    project.mkdir()
    external_state.mkdir()
    (project / ".ces").symlink_to(external_state, target_is_directory=True)

    with pytest.raises(typer.BadParameter, match="symlinked .ces"):
        _resolve_semantic_project_root(project)


def test_agent_provenance_reads_state_db_without_local_store_side_effects(tmp_path: Path) -> None:
    from ces.review.provenance import load_agent_provenance

    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    db_path = ces_dir / "state.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE builder_sessions (
                session_id TEXT, project_id TEXT, brief_id TEXT, request TEXT,
                project_mode TEXT, stage TEXT, next_action TEXT, last_action TEXT,
                source_of_truth TEXT, critical_flows TEXT, manifest_id TEXT,
                runtime_manifest_id TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE builder_briefs (
                brief_id TEXT, project_id TEXT, request TEXT, project_mode TEXT,
                manifest_id TEXT, created_at TEXT
            );
            CREATE TABLE manifests (manifest_id TEXT, project_id TEXT, description TEXT);
            CREATE TABLE runtime_executions (
                manifest_id TEXT, project_id TEXT, runtime_name TEXT,
                reported_model TEXT, invocation_ref TEXT
            );
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO builder_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "session-1",
                "default",
                "brief-1",
                "implement semantic review",
                "brownfield",
                "done",
                "review",
                "build",
                "[]",
                "[]",
                "manifest-1",
                "manifest-1",
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO builder_briefs VALUES (?, ?, ?, ?, ?, ?)",
            ("brief-1", "default", "request", "brownfield", "manifest-1", now),
        )
        conn.execute(
            "INSERT INTO manifests VALUES (?, ?, ?)",
            ("manifest-1", "default", "semantic review manifest"),
        )
        conn.execute(
            "INSERT INTO runtime_executions VALUES (?, ?, ?, ?, ?)",
            ("manifest-1", "default", "codex", "gpt-5.5", "run-1"),
        )
        conn.commit()
    finally:
        conn.close()

    before = db_path.read_bytes()
    provenance = load_agent_provenance(tmp_path)
    after = db_path.read_bytes()

    assert before == after
    assert provenance.mode == "ces_builder"
    assert provenance.build_id == "run-1"
    assert provenance.manifest_id == "manifest-1"
    assert provenance.runtime == "codex"
    assert provenance.model == "gpt-5.5"
    assert "session_id:session-1" in provenance.source_refs


def test_file_classifier_covers_primary_roles_and_source_areas() -> None:
    from ces.review.file_classifier import classify_path

    cases = {
        "uv.lock": ("lockfile", "packaging", "unknown", True),
        ".github/workflows/ci.yml": ("ci", "ci", "yaml", False),
        "pyproject.toml": ("config", "packaging", "toml", False),
        "docs/guide.md": ("doc", "docs", "markdown", False),
        "tests/test_runner.py": ("test", "tests", "python", False),
        "src/ces/execution/runner.py": ("source", "execution", "python", False),
        "src/ces/cli/app.py": ("source", "cli", "python", False),
        "src/ces/local_store/store.py": ("source", "persistence", "python", False),
        "src/ces/harness/review.py": ("source", "harness", "python", False),
        "src/ces/verification/proof_card.py": ("source", "verification", "python", False),
        "src/ces/intake/contracts.py": ("source", "intake", "python", False),
        "src/ces/control/services/audit.py": ("source", "governance", "python", False),
        "src/ces/review/service.py": ("source", "review", "python", False),
        "src/ces/observability/metrics.py": ("source", "sensors", "python", False),
        "src/ces/brownfield/register.py": ("source", "brownfield", "python", False),
        "src/ces/emergency/sla.py": ("source", "safety", "python", False),
        "assets/logo.png": ("asset", "assets", "unknown", False),
        "build/generated/client.py": ("source", "source", "python", False),
        "tools/credential_loader.py": ("source", "security", "python", False),
        "tools/runtime_adapter.py": ("source", "runtime", "python", False),
    }

    for relpath, expected in cases.items():
        classification = classify_path(relpath)
        assert (
            classification.role,
            classification.conceptual_area,
            classification.language,
            classification.lockfile,
        ) == expected

    assert classify_path("build/generated/client.py").generated is True
    assert classify_path("unknown.bin").signals == ("no deterministic classifier matched",)


def test_intent_coverage_extracts_contract_requirements_and_statuses(tmp_path: Path) -> None:
    from ces.review.intent_coverage import build_intent_coverage
    from ces.review.models import ChangedFile, DiffIndex, DiffStats, VerificationCommandResult, VerificationSummary

    (tmp_path / ".ces" / "contracts").mkdir(parents=True)
    (tmp_path / ".ces" / "contracts" / "latest.json").write_text(
        json.dumps(
            {
                "objective": "REQ-42 update review_cmd command",
                "acceptance_criteria": [
                    {"text": "tests cover cli behavior"},
                    "defer non-goal telemetry",
                ],
                "behavior_delta": {"changed": ["review command emits json"]},
            }
        ),
        encoding="utf-8",
    )
    diff_index = DiffIndex(
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="abc",
        stats=DiffStats(files_changed=2, insertions=12, deletions=1),
        changed_files=(
            ChangedFile(path="src/ces/cli/review_cmd.py", classification={"role": "source", "conceptual_area": "cli"}),
            ChangedFile(
                path="tests/unit/test_review_cmd.py", classification={"role": "test", "conceptual_area": "tests"}
            ),
        ),
    )
    verification = VerificationSummary(
        status="passed",
        commands=(VerificationCommandResult(command="pytest tests/unit/test_review_cmd.py", status="passed"),),
    )

    coverage = build_intent_coverage(
        tmp_path,
        diff_index,
        verification,
        objective="REQ-1 cli review command",
        deferred_scope=("telemetry",),
    )

    by_id = {item.requirement_id: item for item in coverage.items}
    assert by_id["REQ-1"].status == "implemented"
    assert set(by_id["REQ-1"].changed_files) == {"src/ces/cli/review_cmd.py", "tests/unit/test_review_cmd.py"}
    assert by_id["REQ-42"].status == "implemented"
    assert any(item.status == "intentionally_deferred" for item in coverage.items)
    assert coverage.sources[:2] == ("objective", "execution_contract")
    assert coverage.summary["implemented"] >= 2


def test_risk_map_scores_high_risk_patterns_and_review_path() -> None:
    from ces.review.models import ChangedFile, DiffIndex, DiffStats, VerificationSummary
    from ces.review.risk import build_review_path, build_risk_map

    diff_index = DiffIndex(
        base_ref="HEAD~1",
        head_ref="HEAD",
        diff_fingerprint="abc",
        warnings=("diff was truncated",),
        stats=DiffStats(files_changed=5, insertions=800, deletions=30),
        changed_files=(
            ChangedFile(
                path="src/ces/execution/runner.py",
                status="modified",
                additions=620,
                deletions=10,
                classification={"role": "source", "conceptual_area": "execution"},
                content_excerpt="subprocess.run(command, shell=True) secret token write_text unlink asyncio",
            ),
            ChangedFile(
                path="pyproject.toml",
                status="modified",
                additions=3,
                classification={"role": "config", "conceptual_area": "packaging"},
            ),
            ChangedFile(
                path="uv.lock",
                status="modified",
                additions=10,
                classification={"role": "lockfile", "conceptual_area": "packaging", "lockfile": True},
            ),
            ChangedFile(
                path="docs/old.md",
                status="deleted",
                deletions=2,
                classification={"role": "doc", "conceptual_area": "docs"},
            ),
            ChangedFile(
                path="dist/generated.js",
                additions=3,
                classification={"role": "generated", "conceptual_area": "unknown", "generated": True},
            ),
        ),
    )

    risk_map = build_risk_map(diff_index, VerificationSummary(status="failed"))
    review_path = build_review_path(risk_map)

    assert risk_map.overall_level == "critical"
    assert risk_map.review_first[0].path == "src/ces/execution/runner.py"
    assert any("subprocess" in checkpoint.lower() for checkpoint in risk_map.checkpoints)
    assert any(area.area == "packaging" for area in risk_map.area_risks)
    assert review_path.steps[0].target == "src/ces/execution/runner.py"
    assert (
        build_review_path(build_risk_map(diff_index.model_copy(update={"changed_files": ()}), VerificationSummary()))
        .steps[0]
        .kind
        == "summary"
    )


def test_verification_summary_handles_missing_invalid_and_command_shapes(tmp_path: Path) -> None:
    from ces.review.verification import load_verification_summary, verification_evidence_fingerprint

    missing = load_verification_summary(tmp_path)
    assert missing.status == "not_run"
    assert verification_evidence_fingerprint(tmp_path) == "latest-verification:absent"

    symlink_project = tmp_path / "symlink-project"
    (symlink_project / ".ces").mkdir(parents=True)
    symlink_target = tmp_path / "outside-verification.json"
    symlink_target.write_text("{}", encoding="utf-8")
    (symlink_project / ".ces" / "latest-verification.json").symlink_to(symlink_target)
    assert verification_evidence_fingerprint(symlink_project) == "latest-verification:symlinked"
    assert load_verification_summary(symlink_project).status == "not_run"

    latest = tmp_path / ".ces" / "latest-verification.json"
    latest.parent.mkdir()
    latest.write_text("not-json", encoding="utf-8")
    invalid = load_verification_summary(tmp_path)
    assert invalid.status == "unknown"

    latest.write_text(json.dumps({"verification": "not-a-mapping"}), encoding="utf-8")
    non_mapping = load_verification_summary(tmp_path)
    assert non_mapping.status == "unknown"

    latest.write_text(
        json.dumps(
            {
                "verification": {
                    "passed": False,
                    "commands": [
                        {"command": "pytest", "exit_code": 1, "duration_seconds": 1.25, "stderr_summary": "failed"},
                        {"command": "ruff", "skipped": True},
                        "custom smoke",
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    failed = load_verification_summary(tmp_path)
    assert failed.status == "failed"
    assert [command.status for command in failed.commands] == ["failed", "skipped", "unknown"]
    assert verification_evidence_fingerprint(tmp_path).startswith("latest-verification:sha256:")


def test_diff_index_covers_worktree_statuses_untracked_and_helpers(tmp_path: Path) -> None:
    from ces.review.diff_index import (
        _git_optional,
        _normalize_rename_path,
        _parse_numstat,
        _path_from_diff_header,
        _safe_ref,
        build_diff_index,
    )

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "src" / "ces" / "review").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "ces" / "review" / "alpha.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "old.md").write_text("old\n", encoding="utf-8")
    (tmp_path / "remove.txt").write_text("remove me\n", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"PNG base")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")

    (tmp_path / "src" / "ces" / "review" / "alpha.py").write_text("import subprocess\nVALUE = 2\n", encoding="utf-8")
    _git(tmp_path, "mv", "docs/old.md", "docs/new.md")
    (tmp_path / "remove.txt").unlink()
    (tmp_path / "image.png").write_bytes(b"PNG changed")
    (tmp_path / "untracked.py").write_text("print('new')\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "ignored.json").write_text("{}\n", encoding="utf-8")

    diff_index = build_diff_index(tmp_path, base_ref="HEAD", include_untracked=True)
    by_path = {item.path: item for item in diff_index.changed_files}

    assert by_path["src/ces/review/alpha.py"].status == "modified"
    assert by_path["src/ces/review/alpha.py"].content_hash
    assert "subprocess" in by_path["src/ces/review/alpha.py"].content_excerpt
    assert by_path["docs/new.md"].status == "renamed"
    assert by_path["docs/new.md"].old_path == "docs/old.md"
    assert by_path["remove.txt"].status == "deleted"
    assert by_path["remove.txt"].patch_available is False
    assert by_path["image.png"].binary is True
    assert by_path["image.png"].content_excerpt == ""
    assert by_path["untracked.py"].status == "untracked"
    assert by_path["untracked.py"].additions == 1
    assert ".ces/ignored.json" not in by_path
    assert diff_index.head_ref == "WORKTREE"
    assert diff_index.diff_fingerprint

    assert _safe_ref(" HEAD ") == "HEAD"
    with pytest.raises(ValueError, match="Invalid git ref"):
        _safe_ref("-bad")
    assert _git_optional(tmp_path, "rev-parse", "--verify", "does-not-exist") is None
    assert _parse_numstat("1\t2\tsrc/{old => new}.py\n-\t-\tassets/logo.png\n") == {
        "src/new.py": (1, 2, False),
        "assets/logo.png": (0, 0, True),
    }
    assert _normalize_rename_path("src/{old => new}/file.py") == "src/new/file.py"
    assert _path_from_diff_header("diff --git a/src/a.py b/src/a.py") == "src/a.py"


def test_diff_index_empty_repo_diff_warns(tmp_path: Path) -> None:
    from ces.review.diff_index import build_diff_index

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")

    diff_index = build_diff_index(tmp_path, base_ref="HEAD", include_untracked=False)

    assert diff_index.changed_files == ()
    assert diff_index.stats.files_changed == 0
    assert diff_index.warnings == ("No changed files detected for the requested diff.",)


def test_github_comment_posts_new_comment_and_surfaces_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ces.review.github_comment as github_comment_module
    from ces.execution.processes import ProcessResult
    from ces.review.github_comment import post_github_comment
    from ces.review.models import GithubReviewComment

    calls: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        del kwargs
        command_tuple = tuple(str(part) for part in command)
        calls.append(command_tuple)
        if command_tuple == ("gh", "api", "user", "--jq", ".login"):
            return ProcessResult(command=command_tuple, exit_code=0, stdout="vega\n", stderr="")
        if command_tuple[:2] == ("gh", "api") and "issues/77/comments" in command_tuple[2]:
            return ProcessResult(command=command_tuple, exit_code=0, stdout="\n", stderr="")
        if command_tuple[:3] == ("gh", "pr", "comment"):
            return ProcessResult(command=command_tuple, exit_code=0, stdout="created\n", stderr="")
        return ProcessResult(command=command_tuple, exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(github_comment_module, "run_sync_command", fake_run)
    comment = GithubReviewComment(review_id="review-1", body="body", update_marker="marker")

    post_github_comment(comment, pr=77, repo_root=tmp_path, update_existing=True)

    assert any(command[:3] == ("gh", "pr", "comment") for command in calls)
    assert not any("--edit-last" in command for command in calls)
    assert any(command[:3] == ("gh", "pr", "comment") and "--body-file" in command for command in calls)

    def failing_run(command, **kwargs):
        del kwargs
        command_tuple = tuple(str(part) for part in command)
        return ProcessResult(command=command_tuple, exit_code=1, stdout="", stderr="boom")

    monkeypatch.setattr(github_comment_module, "run_sync_command", failing_run)
    with pytest.raises(RuntimeError, match="boom"):
        post_github_comment(comment, pr=77, repo_root=tmp_path, update_existing=False)


def test_diff_index_error_paths_fail_closed(tmp_path: Path) -> None:
    from ces.review.diff_index import (
        _git as diff_git,
    )
    from ces.review.diff_index import (
        _parse_name_status,
        _safe_excerpt,
        _safe_ref,
        build_diff_index,
        resolve_git_root,
    )

    with pytest.raises(ValueError, match="Cannot generate semantic review"):
        resolve_git_root(tmp_path)

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")

    with pytest.raises(ValueError, match="Invalid git ref"):
        build_diff_index(tmp_path, base_ref="-bad")
    with pytest.raises(ValueError):
        diff_git(tmp_path, "definitely-not-a-git-command")
    assert _safe_ref(None) is None
    assert _parse_name_status("malformed", {}, tmp_path, "", head_ref=None) == []
    assert _safe_excerpt(tmp_path / "missing.py", binary=False, deleted=False) == ""


def test_github_comment_lookup_failures_are_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ces.review.github_comment as github_comment_module
    from ces.execution.processes import ProcessResult
    from ces.review.github_comment import post_github_comment
    from ces.review.models import GithubReviewComment

    comment = GithubReviewComment(review_id="review-1", body="body", update_marker="marker")

    def failing_viewer(command, **kwargs):
        del kwargs
        command_tuple = tuple(str(part) for part in command)
        return ProcessResult(command=command_tuple, exit_code=1, stdout="", stderr="viewer boom")

    monkeypatch.setattr(github_comment_module, "run_sync_command", failing_viewer)
    with pytest.raises(RuntimeError, match="viewer boom"):
        post_github_comment(comment, pr=88, repo_root=tmp_path, update_existing=True)

    def failing_lookup(command, **kwargs):
        del kwargs
        command_tuple = tuple(str(part) for part in command)
        if command_tuple == ("gh", "api", "user", "--jq", ".login"):
            return ProcessResult(command=command_tuple, exit_code=0, stdout="vega\n", stderr="")
        return ProcessResult(command=command_tuple, exit_code=1, stdout="", stderr="lookup boom")

    monkeypatch.setattr(github_comment_module, "run_sync_command", failing_lookup)
    with pytest.raises(RuntimeError, match="lookup boom"):
        post_github_comment(comment, pr=88, repo_root=tmp_path, update_existing=True)


def test_github_comment_update_failure_surfaces_patch_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ces.review.github_comment as github_comment_module
    from ces.execution.processes import ProcessResult
    from ces.review.github_comment import post_github_comment
    from ces.review.models import GithubReviewComment

    def fake_run(command, **kwargs):
        del kwargs
        command_tuple = tuple(str(part) for part in command)
        if command_tuple == ("gh", "api", "user", "--jq", ".login"):
            return ProcessResult(command=command_tuple, exit_code=0, stdout="vega\n", stderr="")
        if command_tuple[:2] == ("gh", "api") and "issues/89/comments" in command_tuple[2]:
            return ProcessResult(command=command_tuple, exit_code=0, stdout="456\n", stderr="")
        if command_tuple[:3] == ("gh", "api", "repos/:owner/:repo/issues/comments/456"):
            return ProcessResult(command=command_tuple, exit_code=1, stdout="", stderr="patch boom")
        return ProcessResult(command=command_tuple, exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(github_comment_module, "run_sync_command", fake_run)
    comment = GithubReviewComment(review_id="review-1", body="body", update_marker="marker")

    with pytest.raises(RuntimeError, match="patch boom"):
        post_github_comment(comment, pr=89, repo_root=tmp_path, update_existing=True)
