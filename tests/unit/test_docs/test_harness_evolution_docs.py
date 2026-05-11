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
    assert ".ces/state.db" in text


def test_quick_reference_card_lists_harness_commands() -> None:
    text = (ROOT / "docs" / "Quick_Reference_Card.md").read_text(encoding="utf-8")

    assert "ces harness init --dry-run" in text
    assert "ces harness changes validate" in text
    assert "ces harness changes add" in text
    assert "ces harness changes list" in text
    assert "ces harness changes show" in text
