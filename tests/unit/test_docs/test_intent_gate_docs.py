from __future__ import annotations

from pathlib import Path

_DOC_PATH = Path(__file__).parents[3] / "docs" / "Intent_Gate.md"


def test_intent_gate_operator_docs_cover_decisions_and_cli_controls() -> None:
    doc_text = _DOC_PATH.read_text(encoding="utf-8").lower()

    for required_phrase in (
        "ask",
        "assume_and_proceed",
        "proceed",
        "blocked",
        "--reverse-preflight",
        "--acceptance",
        "non-interactive",
    ):
        assert required_phrase in doc_text
