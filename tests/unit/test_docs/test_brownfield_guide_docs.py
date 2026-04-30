"""Doc verification for brownfield workflow guidance."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_brownfield_guide_covers_builder_first_and_expert_boundary() -> None:
    guide = (ROOT / "docs" / "Brownfield_Guide.md").read_text(encoding="utf-8")
    lowered = guide.lower()

    assert "builder-first" in lowered
    assert "expert workflow" in lowered
    assert "Operator Playbook" in guide
    assert "ces continue" in guide
    assert "ces explain --view brownfield" in guide
    assert "ces brownfield register" in guide
    assert "ces brownfield promote" in guide


def test_brownfield_guide_routes_general_workflow_questions_to_operator_playbook() -> None:
    guide = (ROOT / "docs" / "Brownfield_Guide.md").read_text(encoding="utf-8")

    assert (
        "Use the [Operator Playbook](Operator_Playbook.md) when you need the broader "
        "builder-first versus expert workflow boundary for a single request." in guide
    )


def test_brownfield_review_example_matches_supported_cli_shape() -> None:
    guide = (ROOT / "docs" / "Brownfield_Guide.md").read_text(encoding="utf-8")
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    review_example = "ces brownfield review OLB-<entry-id> --disposition preserve"

    assert review_example in guide
    assert review_example in getting_started


def test_entry_docs_route_brownfield_work_to_builder_first_then_guide() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    for text in (readme, getting_started):
        assert "ces explain --view brownfield" in text
        assert "ces brownfield review OLB-<entry-id> --disposition preserve" in text
        assert "Brownfield Guide" in text


def test_getting_started_command_reference_summarizes_brownfield_command_group() -> None:
    getting_started = (ROOT / "docs" / "Getting_Started.md").read_text(encoding="utf-8")

    assert "| `ces brownfield ...` |" in getting_started
    assert "Expert legacy behavior capture, review, and promotion" in getting_started


def test_readme_command_reference_summarizes_brownfield_command_group() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "| `brownfield ...` |" in readme
    assert "Expert legacy behavior capture, review, and promotion" in readme
