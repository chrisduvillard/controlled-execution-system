"""Doc verification for operator workflow guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_operator_playbook_exists_and_covers_workflow_boundaries() -> None:
    playbook = ROOT / "docs" / "Operator_Playbook.md"
    assert playbook.is_file()
    text = playbook.read_text(encoding="utf-8")
    assert "builder-first" in text.lower()
    assert "expert workflow" in text.lower()
    assert "ces report builder" in text
    assert "validation evidence" in text.lower()
    assert "ces status --expert" in text
    assert "ces status --expert --watch" in text
    assert "ces audit --limit 20" in text
    assert 'ces emergency declare "Security incident detected"' in text
    assert "system-wide visibility" in text.lower()
    assert "incident response" in text.lower()
    assert "ces emergency resolve --" not in text


def test_operator_playbook_validation_evidence_uses_supported_audit_example() -> None:
    text = (ROOT / "docs" / "Operator_Playbook.md").read_text(encoding="utf-8")

    assert "Operator audit inspection" in text
    assert "Event stream queries around incidents, recoveries, and other governance activity" in text
    assert "ces audit --limit 20" in text


def test_operator_playbook_routes_brownfield_work_back_to_builder_first() -> None:
    text = (ROOT / "docs" / "Operator_Playbook.md").read_text(encoding="utf-8")

    assert "ces explain --view brownfield" in text
    assert "ces brownfield review OLB-<entry-id> --disposition preserve" in text
    assert "Brownfield Guide" in text
    assert "named legacy-behavior decision" in text
    assert "explicit brownfield governance surfaces" in text


def test_entry_docs_route_operators_to_builder_reports_and_expert_handoff() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "builder-first" in readme.lower()
    assert "expert workflow" in readme.lower()
    assert "ces report builder" in readme
    assert "ces why" in readme
    assert "ces recover --dry-run" in readme
    assert "ces verify" in readme
    assert "ces complete" in readme
    assert "Operator Playbook" in readme
    assert "ces status --expert" in readme
    assert "ces status --expert --watch" in readme
    assert "ces audit --limit 20" in readme
    assert 'ces emergency declare "Security incident detected"' in readme
    assert "Operations Runbook" in readme
    assert "builder-first" in getting_started.lower()
    assert "expert workflow" in getting_started.lower()
    assert "ces report builder" in getting_started
    assert "ces why" in getting_started
    assert "ces recover --dry-run" in getting_started
    assert "ces verify" in getting_started
    assert "ces complete" in getting_started
    assert "ces status --expert" in getting_started
    assert "ces status --expert --watch" in getting_started
    assert "ces audit --limit 20" in getting_started
    assert 'ces emergency declare "Security incident detected"' in getting_started
    assert "Operations Runbook" in getting_started


def test_getting_started_command_reference_uses_supported_operations_examples() -> None:
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "| `ces audit` | Expert operations audit inspection;" in getting_started
    assert "`ces audit --limit 20`" in getting_started
    assert "| `ces audit --limit 20` |" not in getting_started
    assert "| `ces emergency declare` | Expert operations emergency declaration;" in getting_started
    assert '`ces emergency declare "Security incident detected"`' in getting_started
    assert '| `ces emergency declare "Security incident detected"` |' not in getting_started


def test_readme_command_reference_uses_supported_operations_examples() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "| `audit` | Expert operations audit inspection;" in readme
    assert "`ces audit --limit 20`" in readme
    assert "| `audit --limit 20` |" not in readme
    assert "| `emergency declare` | Expert operations emergency declaration;" in readme
    assert '`ces emergency declare "Security incident detected"`' in readme
    assert '| `emergency declare "Security incident detected"` |' not in readme
    assert "| `emergency ...` | Expert operations kill switch and emergency controls |" not in readme
