"""Tests for harness evolution SQLite persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ces.harness_evolution.models import HarnessChangeManifest, HarnessChangeVerdict
from ces.harness_evolution.repository import HarnessEvolutionRepository
from ces.local_store import LocalProjectStore


def _manifest(change_id: str = "hchg-repository-test", *, status: str = "draft") -> HarnessChangeManifest:
    return HarnessChangeManifest.model_validate(
        {
            "change_id": change_id,
            "title": "Reject proxy validation",
            "component_type": "tool_policy",
            "files_changed": ["src/ces/harness/policy.md"],
            "evidence_refs": ["analysis:proxy-validation"],
            "failure_pattern": "Proxy validation was accepted.",
            "root_cause_hypothesis": "The policy did not distinguish real evaluators from proxy checks.",
            "predicted_fixes": ["Proxy-only checks are rejected."],
            "predicted_regressions": ["Some valid lightweight checks may need extra justification."],
            "validation_plan": ["Run focused dogfood transcript analysis."],
            "rollback_condition": "Rollback if false blocks increase.",
            "status": status,
        }
    )


def _repo(tmp_path: Path) -> HarnessEvolutionRepository:
    store = LocalProjectStore(tmp_path / ".ces" / "state.db", project_id="proj")
    return HarnessEvolutionRepository(store)


def test_save_get_and_list_harness_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = _manifest()

    record = repo.save_change(manifest)

    assert record.change_id == manifest.change_id
    assert record.manifest == manifest
    assert len(record.manifest_hash) == 64
    assert repo.get_change(manifest.change_id) == record
    assert repo.list_changes() == [record]
    assert repo.list_changes(status="active") == []


def test_save_change_is_upsert_and_updates_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.save_change(_manifest(status="draft"))

    updated = repo.save_change(_manifest(status="active"))

    assert updated.status == "active"
    assert repo.get_change(updated.change_id).status == "active"  # type: ignore[union-attr]
    assert len(repo.list_changes()) == 1


def test_save_and_list_harness_change_verdicts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = _manifest()
    repo.save_change(manifest)
    verdict = HarnessChangeVerdict.model_validate(
        {
            "change_id": manifest.change_id,
            "observed_fixes": ["Proxy-only checks are rejected."],
            "missed_fixes": [],
            "observed_predicted_regressions": [],
            "unexpected_regressions": [],
            "verdict": "keep",
            "rationale": "Observed effect matches the predicted fix.",
        }
    )

    record = repo.save_verdict(verdict)

    assert record.change_id == manifest.change_id
    assert record.verdict == "keep"
    assert record.verdict_payload == verdict
    assert repo.list_verdicts(manifest.change_id) == [record]


def test_save_verdict_returns_inserted_record_when_created_at_is_out_of_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = _manifest()
    repo.save_change(manifest)
    later = HarnessChangeVerdict.model_validate(
        {
            "change_id": manifest.change_id,
            "observed_fixes": ["Later observation."],
            "missed_fixes": [],
            "observed_predicted_regressions": [],
            "unexpected_regressions": [],
            "verdict": "keep",
            "rationale": "First inserted but later in logical time.",
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
    )
    earlier = HarnessChangeVerdict.model_validate(
        {
            "change_id": manifest.change_id,
            "observed_fixes": ["Earlier observation."],
            "missed_fixes": [],
            "observed_predicted_regressions": [],
            "unexpected_regressions": [],
            "verdict": "revise",
            "rationale": "Second inserted but earlier in logical time.",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )

    later_record = repo.save_verdict(later)
    earlier_record = repo.save_verdict(earlier)

    assert later_record.id != earlier_record.id
    assert later_record.verdict_payload == later
    assert earlier_record.verdict_payload == earlier
    assert earlier_record.verdict == "revise"
    assert [record.verdict for record in repo.list_verdicts(manifest.change_id)] == ["revise", "keep"]


def test_saving_verdict_for_unknown_change_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    verdict = HarnessChangeVerdict.model_validate(
        {
            "change_id": "hchg-missing",
            "observed_fixes": [],
            "missed_fixes": ["No run yet."],
            "observed_predicted_regressions": [],
            "unexpected_regressions": [],
            "verdict": "inconclusive",
            "rationale": "No persisted change exists.",
        }
    )

    with pytest.raises(ValueError, match="unknown harness change"):
        repo.save_verdict(verdict)
