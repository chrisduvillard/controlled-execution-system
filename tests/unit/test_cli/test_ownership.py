"""Tests for local actor and CODEOWNERS ownership helpers."""

from __future__ import annotations

from ces.cli.ownership import matching_codeowners, parse_codeowners, resolve_actor


def test_resolve_actor_prefers_ces_actor(monkeypatch) -> None:
    monkeypatch.setenv("CES_ACTOR", "alice@example.com")

    assert resolve_actor() == "alice@example.com"


def test_parse_and_match_codeowners() -> None:
    entries = parse_codeowners("src/ @team-backend\n*.md @docs @alice\n")

    assert matching_codeowners("src/ces/app.py", entries) == ("@team-backend",)
    assert matching_codeowners("README.md", entries) == ("@docs", "@alice")
