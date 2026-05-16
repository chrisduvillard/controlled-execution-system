"""Contracts for CES intake execution-contract flow."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ces.cli import app
from ces.intake.contracts import (
    BehaviorDelta,
    ContractSource,
    ContractSourceKind,
    ExecutionContract,
    ExecutionContractRepository,
    IntakeNormalizer,
    RequiredEvidence,
    SourceReader,
    ValidationSeverity,
    validate_execution_contract,
)
from ces.verification.proof_card import build_proof_card

runner = CliRunner()


def test_inline_intake_normalizes_to_execution_contract(tmp_path: Path) -> None:
    contract = IntakeNormalizer().from_inline("Add CSV invoice notes", project_root=tmp_path)

    assert contract.contract_id.startswith("EC-")
    assert contract.objective == "Add CSV invoice notes"
    assert contract.source.kind is ContractSourceKind.INLINE
    assert contract.source.label == "inline intent"
    assert "Add CSV invoice notes" in contract.acceptance_criteria
    assert "Do not expand scope beyond: Add CSV invoice notes" in contract.non_goals
    assert "Preserve existing behavior unless explicitly changed." in contract.behavior_delta.preserved
    assert contract.required_evidence
    assert "verification-before-completion" in contract.policies


def test_prd_file_intake_extracts_headings_and_behavior_delta(tmp_path: Path) -> None:
    prd = tmp_path / "docs" / "prd.md"
    prd.parent.mkdir()
    prd.write_text(
        """# Add CSV invoice notes

## Problem
Users cannot export invoice notes.

## Success Criteria
- CSV export includes invoice notes.
- Existing invoices without notes still export.

## Non-Goals
- Do not redesign billing.

## Preserved Behavior
- Existing CSV column order remains stable.

## Required Evidence
- Regression test for invoices without notes.
""",
        encoding="utf-8",
    )

    contract = IntakeNormalizer().from_prd(prd, project_root=tmp_path)

    assert contract.objective == "Add CSV invoice notes"
    assert contract.problem == "Users cannot export invoice notes."
    assert contract.acceptance_criteria == (
        "CSV export includes invoice notes.",
        "Existing invoices without notes still export.",
    )
    assert contract.non_goals == ("Do not redesign billing.",)
    assert contract.behavior_delta.preserved == ("Existing CSV column order remains stable.",)
    assert contract.required_evidence[0].description == "Regression test for invoices without notes."


def test_contract_repository_writes_safe_project_local_json_and_markdown(tmp_path: Path) -> None:
    contract = IntakeNormalizer().from_inline("Add CSV invoice notes", project_root=tmp_path)

    saved = ExecutionContractRepository(tmp_path).save(contract)

    assert saved.json_path == tmp_path / ".ces" / "contracts" / f"{contract.contract_id}.json"
    assert saved.markdown_path == tmp_path / "docs" / "contracts" / f"{contract.contract_id}.md"
    assert saved.latest_path == tmp_path / ".ces" / "contracts" / "latest.json"
    payload = json.loads(saved.json_path.read_text(encoding="utf-8"))
    assert payload["contract_id"] == contract.contract_id
    assert payload["source"]["kind"] == "inline"
    assert "# Execution Contract" in saved.markdown_path.read_text(encoding="utf-8")


def test_contract_repository_rejects_symlinked_ces_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".ces").symlink_to(outside, target_is_directory=True)
    contract = IntakeNormalizer().from_inline("Add CSV invoice notes", project_root=tmp_path)

    with pytest.raises(ValueError, match="Refusing to write contracts through symlinked .ces"):
        ExecutionContractRepository(tmp_path).save(contract)


def test_github_issue_reader_uses_gh_json_without_framework_importers(tmp_path: Path) -> None:
    completed = type(
        "Completed",
        (),
        {
            "returncode": 0,
            "stdout": json.dumps(
                {
                    "number": 123,
                    "title": "Add CSV invoice notes",
                    "body": "## Success Criteria\n- CSV includes notes",
                    "url": "https://github.com/acme/app/issues/123",
                }
            ),
            "stderr": "",
        },
    )()

    with (
        patch("ces.intake.contracts.shutil.which", return_value="/usr/bin/gh"),
        patch("ces.intake.contracts.subprocess.run", return_value=completed) as run,
    ):
        source = SourceReader().read_github_issue("123")

    assert source.kind is ContractSourceKind.GITHUB_ISSUE
    assert source.label == "GitHub issue #123"
    assert source.url == "https://github.com/acme/app/issues/123"
    assert source.content.startswith("# Add CSV invoice notes")
    assert run.call_args.args[0][:4] == ["/usr/bin/gh", "issue", "view", "123"]


def test_source_reader_rejects_invalid_inputs(tmp_path: Path) -> None:
    reader = SourceReader()
    with pytest.raises(ValueError, match="inline intake text cannot be empty"):
        reader.read_inline("   ")
    with pytest.raises(ValueError, match="PRD file not found"):
        reader.read_prd("missing.md", project_root=tmp_path)
    txt = tmp_path / "prd.txt"
    txt.write_text("not markdown", encoding="utf-8")
    with pytest.raises(ValueError, match="only accepts Markdown"):
        reader.read_prd(txt, project_root=tmp_path)
    empty = tmp_path / "empty.md"
    empty.write_text("  ", encoding="utf-8")
    with pytest.raises(ValueError, match="PRD file is empty"):
        reader.read_prd(empty, project_root=tmp_path)


def test_github_issue_reader_reports_missing_gh_and_failed_gh() -> None:
    reader = SourceReader()
    with pytest.raises(ValueError, match="GitHub issue reference cannot be empty"):
        reader.read_github_issue("   ")
    with (
        patch("ces.intake.contracts.shutil.which", return_value=None),
        pytest.raises(RuntimeError, match="requires the GitHub CLI"),
    ):
        reader.read_github_issue("123")

    completed = type("Completed", (), {"returncode": 2, "stdout": "", "stderr": "not found"})()
    with (
        patch("ces.intake.contracts.shutil.which", return_value="/usr/bin/gh"),
        patch("ces.intake.contracts.subprocess.run", return_value=completed),
        pytest.raises(RuntimeError, match="Could not read GitHub issue 123: not found"),
    ):
        reader.read_github_issue("123")


def test_contract_repository_load_latest_and_missing_contract_errors(tmp_path: Path) -> None:
    repo = ExecutionContractRepository(tmp_path)
    with pytest.raises(ValueError, match="No intake execution contract found"):
        repo.load_latest()
    with pytest.raises(ValueError, match="Execution contract not found"):
        repo.load("EC-MISSING")

    saved = repo.save(IntakeNormalizer().from_inline("Document CI pipeline", project_root=tmp_path))
    assert repo.load_latest().contract_id == saved.contract.contract_id
    assert repo.load(saved.contract.contract_id).objective == "Document CI pipeline"


def test_normalizer_extracts_risks_evidence_kinds_and_change_classes(tmp_path: Path) -> None:
    prd = tmp_path / "prd.md"
    prd.write_text(
        """# Fix auth deployment regression

## Success Criteria
Manual inspection confirms auth works.

## Added Behavior
The deploy pipeline records auth smoke output.

## Modified Behavior
Billing migration retries once.

## Removed Behavior
Old insecure retry path is removed.

## Unknown Behavior
Database replica lag is unverified.

## Required Evidence
- Manual inspection screenshot.
- Artifact file with deploy output.
- Command run for auth smoke.
- Regression test for billing migration.

## Risks
- Data migration risk:: Run rollback rehearsal.
""",
        encoding="utf-8",
    )

    contract = IntakeNormalizer().from_prd(prd, project_root=tmp_path)

    assert contract.risks[0].mitigation == "Run rollback rehearsal."
    assert [item.kind.value for item in contract.required_evidence] == [
        "manual_inspection",
        "artifact",
        "command",
        "test",
    ]
    spec = contract.to_spec_document()
    assert spec.frontmatter.signals.primary_change_class == "bug"
    assert spec.frontmatter.signals.blast_radius_hint == "module"
    assert spec.frontmatter.signals.touches_auth is True
    assert spec.frontmatter.signals.touches_billing is False
    assert spec.frontmatter.signals.touches_data is False
    assert spec.stories[0].risk == "B"
    assert "billing" in spec.stories[0].description


def test_contract_validation_blocks_empty_evidence_and_unknown_behavior() -> None:
    contract = ExecutionContract(
        contract_id="EC-TEST",
        source=ContractSource(kind=ContractSourceKind.INLINE, label="inline", content="Do it"),
        objective="Do it",
        problem="Do it",
        acceptance_criteria=("It is done",),
        non_goals=(),
        behavior_delta=BehaviorDelta(),
        required_evidence=(),
        created_at=datetime.now(timezone.utc),
    )

    findings = validate_execution_contract(contract)

    assert any(f.severity is ValidationSeverity.BLOCKER and "required evidence" in f.message for f in findings)
    assert any("behavior delta" in f.message for f in findings)


def test_cli_intake_inline_writes_contract_and_next_commands(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        result = runner.invoke(app, ["intake", "Add CSV invoice notes", "--json"])
        root = Path(cwd)
        latest = root / ".ces" / "contracts" / "latest.json"

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["contract"]["objective"] == "Add CSV invoice notes"
        assert payload["next_commands"] == ["ces build --from-contract", "ces verify", "ces proof", "ces approve"]
        assert latest.is_file()


def test_cli_intake_prd_file_and_show_latest(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        root = Path(cwd)
        prd = root / "prd.md"
        prd.write_text("# Add CSV invoice notes\n\n## Success Criteria\n- CSV includes notes\n", encoding="utf-8")

        create = runner.invoke(app, ["intake", str(prd), "--json"])
        show = runner.invoke(app, ["intake", "show", "--json"])

        assert create.exit_code == 0, create.output
        assert show.exit_code == 0, show.output
        payload = json.loads(show.output)
        assert payload["objective"] == "Add CSV invoice notes"
        assert payload["source"]["kind"] == "prd"


def test_cli_intake_github_issue_writes_contract(tmp_path: Path) -> None:
    source = ContractSource(
        kind=ContractSourceKind.GITHUB_ISSUE,
        label="GitHub issue #123",
        content="# Add CSV invoice notes\n\n## Success Criteria\n- CSV includes notes",
        url="https://github.com/acme/app/issues/123",
    )

    with runner.isolated_filesystem(temp_dir=tmp_path):
        with patch("ces.intake.contracts.SourceReader.read_github_issue", return_value=source):
            result = runner.invoke(app, ["intake", "--from-github-issue", "123", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["contract"]["source"]["kind"] == "github_issue"
        assert payload["contract"]["objective"] == "Add CSV invoice notes"


def test_cli_intake_rejects_external_framework_importer_flags() -> None:
    result = runner.invoke(app, ["intake", "--from-speckit", "specs/001"])

    assert result.exit_code != 0
    assert "No such option: --from-speckit" in result.output


def test_cli_preserves_interview_subcommand() -> None:
    result = runner.invoke(app, ["intake", "interview", "--help"])

    assert result.exit_code == 0
    assert "Phase number" in result.output


def test_cli_build_from_contract_uses_generated_spec_path(tmp_path: Path) -> None:
    with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
        create = runner.invoke(app, ["intake", "Add CSV invoice notes", "--json"])
        assert create.exit_code == 0, create.output
        with patch("ces.cli.run_cmd._preview_from_spec") as preview:
            result = runner.invoke(app, ["build", "--from-contract"])

        assert result.exit_code == 0, result.output
        spec_path = preview.call_args.args[0]
        assert Path(spec_path).as_posix().startswith("docs/specs/EC-")
        assert preview.call_args.kwargs["project_root"] == Path(cwd).resolve()


def test_proof_card_includes_execution_contract_context(tmp_path: Path) -> None:
    contract = IntakeNormalizer().from_inline("Add CSV invoice notes", project_root=tmp_path)
    ExecutionContractRepository(tmp_path).save(contract)

    report = build_proof_card(tmp_path)

    assert report.execution_contract_id == contract.contract_id
    assert report.execution_contract_objective == "Add CSV invoice notes"
    assert "Execution contract exists but completion contract is missing." in report.unproven_areas
    payload = report.to_dict()
    assert payload["execution_contract"]["contract_id"] == contract.contract_id
    assert payload["behavior_delta"]["preserved"] == ["Preserve existing behavior unless explicitly changed."]
