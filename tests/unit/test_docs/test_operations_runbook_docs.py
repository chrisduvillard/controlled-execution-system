"""Doc verification for operator runbook guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_operations_runbook_uses_supported_operator_surfaces() -> None:
    runbook = ROOT / "docs" / "Operations_Runbook.md"
    assert runbook.is_file()

    text = runbook.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "builder-first" in lowered
    for command in ("ces build", "ces continue", "ces explain", "ces explain --view brownfield", "ces status"):
        assert command in text
    assert "ces status --expert" in text
    assert "ces status --expert --watch" in text
    assert "system-wide visibility" in lowered
    assert "incident response" in lowered
    assert "Operator Playbook" in text
    assert "Brownfield Guide" in text
    assert 'ces emergency declare "Security incident detected"' in text
    assert "ces audit --event-type kill_switch --limit 20" in text
    assert "ces audit --event-type recovery --limit 20" in text
    assert "not a public `ces emergency resolve` command" in text
    assert "ces emergency resolve --" not in text
    assert "--verify-integrity" not in text
    assert "emergency declare --reason" not in lowered
