"""Doc verification for the CES quick reference card."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_quick_reference_card_routes_builder_and_expert_workflows() -> None:
    card = (ROOT / "docs" / "Quick_Reference_Card.md").read_text(encoding="utf-8")
    lowered = card.lower()

    assert "builder-first" in lowered
    assert "expert workflow" in lowered
    assert "ces build" in card
    assert "ces continue" in card
    assert "ces explain" in card
    assert "ces status" in card
    assert "ces report builder" in card
    assert "ces manifest" in card
    assert "ces classify" in card
    assert "ces review" in card
    assert "ces triage" in card
    assert "ces approve" in card
    assert "Export a reviewer or audit handoff from the latest builder chain" in card
    assert "Start or resume one delivery request" in card
    assert "`ces build`, `ces continue`, `ces explain`, `ces status`" in card
    assert (
        "Use the [Operator Playbook](Operator_Playbook.md) when you need the "
        "fuller builder-first versus expert workflow boundary for a single request." in card
    )


def test_quick_reference_card_uses_supported_brownfield_and_operations_commands() -> None:
    card = (ROOT / "docs" / "Quick_Reference_Card.md").read_text(encoding="utf-8")

    assert "ces explain --view brownfield" in card
    assert "ces brownfield register" in card
    assert "ces brownfield review OLB-<entry-id> --disposition preserve" in card
    assert "ces brownfield promote" in card
    assert "Brownfield Guide" in card
    assert "Check brownfield context for the active request" in card
    assert "ces status --expert" in card
    assert "ces status --expert --watch" in card
    assert "ces audit --limit 20" in card
    assert 'ces emergency declare "Security incident detected"' in card
    assert "Operations Runbook" in card
    assert "Monitor CES broadly or respond to incidents" in card
    assert "single-request builder loop" in card
    assert (
        "| Monitor CES broadly or respond to incidents | `expert workflow` | "
        "`ces status --expert`, `ces status --expert --watch`, `ces audit`, "
        '`ces emergency declare "Security incident detected"` |' not in card
    )
    assert "ces emergency resolve --" not in card
