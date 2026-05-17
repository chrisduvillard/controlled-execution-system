"""Regression tests for retired FreshCart sample code."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_freshcart_sample_code_is_archived_not_active_example_package() -> None:
    """Historical FreshCart material must not remain as importable active demo code."""

    assert not (ROOT / "examples" / "freshcart").exists()
    assert (ROOT / "docs" / "historical" / "FreshCart_Worked_Example.md").is_file()
    assert (ROOT / "docs" / "FreshCart_Worked_Example.md").is_file()
