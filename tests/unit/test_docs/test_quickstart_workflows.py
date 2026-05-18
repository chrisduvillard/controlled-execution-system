"""Quickstart workflow documentation contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_quickstart_documents_greenfield_and_brownfield_e2e_flows() -> None:
    quickstart = (ROOT / "docs" / "Quickstart.md").read_text(encoding="utf-8")

    assert "Greenfield flow (idea → build → verify → proof)" in quickstart
    assert 'ces build --from-scratch "Create a small task tracker app with add/list/complete tasks, tests, and a README"' in quickstart
    assert "ces verify" in quickstart
    assert "ces proof" in quickstart

    assert "Brownfield flow (existing repo → bounded change)" in quickstart
    assert "ces mri" in quickstart
    assert "ces next" in quickstart
    assert 'ces build "Add invoice notes to CSV exports"' in quickstart
