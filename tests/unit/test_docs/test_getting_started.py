"""Getting Started documentation contract tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_source_checkout_separate_target_pattern_documented() -> None:
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "Using a source checkout against another target directory" in getting_started
    assert "CES_SRC=/path/to/controlled-execution-system" in getting_started
    assert 'CES="$CES_SRC/.venv/bin/ces"' in getting_started
    assert "TARGET=/tmp/ces-taskledger" in getting_started
    assert '"$CES" init --project-root "$TARGET" --yes' in getting_started
    assert '"$CES" build "Create a small Python CLI app named TaskLedger"' in getting_started
    assert '--project-root "$TARGET"' in getting_started
    assert "Do not build inside the CES repository" in getting_started
    assert "runs from your current working directory unless you pass `--project-root`" in getting_started
