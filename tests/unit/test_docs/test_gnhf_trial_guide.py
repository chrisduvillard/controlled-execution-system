"""Verification for the external gnhf trial workflow docs."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_gnhf_trial_guide_documents_guardrails() -> None:
    guide = ROOT / "docs" / "GNHF_Trial_Guide.md"
    assert guide.is_file()

    text = guide.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "safe productivity" in lowered
    assert "builder-first" in lowered
    assert "expert workflows" in lowered or "expert workflow" in lowered
    assert "contributor-side changes" in lowered
    assert "clean sibling worktree" in lowered or "clean clone" in lowered
    assert "clean checkout" in lowered or "clean git worktree" in lowered
    assert "human review" in lowered or "review every" in lowered
    assert "src/ces/control/" in text
    assert "manifest lifecycle" in lowered
    assert "policy decision logic" in lowered
    assert "src/ces/execution/agent_runner.py" in text
    assert "--max-iterations" in text
    assert "--worktree" in text
    for phrase in (
        "approval",
        "triage",
        "review",
        "manifest",
        "audit",
        "kill switch",
        "sandbox",
        "runtime-boundary",
    ):
        assert phrase in lowered


def test_contributor_docs_point_to_gnhf_trial_workflow() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    script = ROOT / "scripts" / "gnhf_trial.sh"

    assert script.is_file()
    assert "GNHF Trial Guide" in readme
    assert "GNHF Trial Guide" in contributing
    assert "clean sibling worktree" in readme.lower() or "clean clone" in readme.lower()
    assert "clean sibling worktree" in contributing.lower() or "clean clone" in contributing.lower()
    assert "builder-first or expert workflows" in readme.lower()
    assert "manifest/policy" in readme.lower()
    assert "approval/triage/review" in readme.lower()
    assert "audit" in readme.lower()
    assert "kill-switch" in readme.lower()
    assert "sandbox" in readme.lower()
    assert "runtime-boundary" in readme.lower()
    assert "review every generated branch manually" in readme.lower()
    assert "scripts/gnhf_trial.sh" in readme
    assert "contributor tooling" in contributing.lower()
    assert "builder-first or expert workflows" in contributing.lower()
    assert "approval/triage/review" in contributing.lower()
    assert "manifest" in contributing.lower()
    assert "audit" in contributing.lower()
    assert "kill-switch" in contributing.lower()
    assert "policy" in contributing.lower()
    assert "sandbox" in contributing.lower()
    assert "runtime-boundary" in contributing.lower()
    assert "review every generated branch manually" in contributing.lower()
    assert "scripts/gnhf_trial.sh" in contributing
