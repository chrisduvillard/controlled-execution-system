"""Docs checks for harness evolution operator boundary."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_operator_playbook_documents_harness_evolution_boundary() -> None:
    text = (ROOT / "docs" / "Operator_Playbook.md").read_text(encoding="utf-8")

    assert "Harness evolution" in text
    assert "local" in text
    assert "not autonomous" in text
    assert "ces harness init --dry-run" in text
    assert "ces harness changes add" in text
    assert "ces harness analyze" in text
    assert "ces harness verdict" in text
    assert "regression-aware verdicts" in text
    assert "post_success_state" in text
    assert "post-success modification" in text
    assert "execution-risk monitor" in text
    assert "repeated identical failures" in text
    assert "Framework reminders" in text
    assert "frm-*" in text
    assert "ces harness memory draft" in text
    assert "ces harness memory archive" in text
    assert "ces harness report --format markdown" in text
    assert "hmem-*" in text
    assert "content hashes" in text
    assert "Execution pipeline consolidation" in text
    assert "ces.execution.pipeline" in text
    assert "ces.control.services.approval_pipeline" in text
    assert "raw dogfood/runtime transcripts" in text
    assert "rollback candidates" in text
    assert ".ces/state.db" in text


def test_quick_reference_card_lists_harness_commands() -> None:
    text = (ROOT / "docs" / "Quick_Reference_Card.md").read_text(encoding="utf-8")

    assert "ces harness init --dry-run" in text
    assert "ces harness changes validate" in text
    assert "ces harness changes add" in text
    assert "ces harness changes list" in text
    assert "ces harness changes show" in text
    assert "ces harness analyze" in text
    assert "ces harness verdict" in text
    assert "ces harness memory draft" in text
    assert "ces harness memory activate" in text
    assert "ces harness memory archive" in text
    assert "ces harness memory list" in text
    assert "ces harness report --format json" in text
    assert "evidence pointers rather than raw transcript replay" in text
    assert "unexpected regressions" in text
    assert "post_success_state" in text
    assert "override is paired with revalidation" in text
    assert "execution_risk_monitor" in text
    assert "compile-only validation" in text
    assert "framework reminders" in text.lower()
    assert "content hashes" in text
    assert "inert, evidence-backed context" in text
