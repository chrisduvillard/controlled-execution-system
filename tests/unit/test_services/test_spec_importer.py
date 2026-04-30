from pathlib import Path

from ces.harness.services.spec_importer import (
    ImportResult,
    SectionMapping,
    SpecImporter,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


def test_importer_produces_mapping_with_missing_sections(tmp_path: Path):
    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=None)
    text = (FIXTURES / "notion-export.md").read_text(encoding="utf-8")
    result = importer.map_sections(text)
    assert isinstance(result, SectionMapping)
    assert "## Non-Goals" in result.missing
    assert "## Risks & Mitigations" in result.missing


def test_importer_uses_llm_mapper_when_provided(tmp_path: Path):
    def fake_mapper(source_text: str, required: tuple[str, ...]) -> dict[str, str]:
        return {
            "## Problem": "## The Problem We're Solving",
            "## Users": "## Who It's For",
            "## Success Criteria": "## What Success Looks Like",
            "## Rollback Plan": "## Rolling Back",
            "## Stories": "## User Stories",
        }

    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=fake_mapper)
    text = (FIXTURES / "notion-export.md").read_text(encoding="utf-8")
    result = importer.map_sections(text)
    assert result.found["## Problem"] == "## The Problem We're Solving"
    assert "## Non-Goals" in result.missing


def test_import_text_rewrites_headers(tmp_path: Path):
    def fake_mapper(source_text, required):
        return {"## Problem": "## The Problem We're Solving"}

    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=fake_mapper)
    text = (FIXTURES / "notion-export.md").read_text(encoding="utf-8")
    result = importer.import_text(text)
    assert isinstance(result, ImportResult)
    assert "## Problem" in result.rewritten_text


def test_rewrite_headers_skips_identity_mapping(tmp_path: Path):
    """When canonical == source_header in the mapping, rewrite_headers leaves the text untouched.

    Covers the `if canonical == source_header: continue` branch — fires whenever
    map_sections found a header verbatim (no rewrite needed).
    """
    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=None)
    source = "## Problem\n\nSome problem text.\n"
    mapping = SectionMapping(found={"## Problem": "## Problem"}, missing=())
    assert importer.rewrite_headers(source, mapping) == source


def test_rewrite_headers_does_not_touch_prose_mentions(tmp_path: Path):
    # A source doc where the header string also appears inside paragraph text.
    source = (
        "## The Problem We're Solving\n"
        "Operators need a probe.\n"
        "\n"
        "As a reminder, the '## The Problem We're Solving' section above\n"
        "describes our problem. This mention must NOT be rewritten.\n"
    )

    def mapper(src: str, required: tuple[str, ...]) -> dict[str, str]:
        return {"## Problem": "## The Problem We're Solving"}

    importer = SpecImporter(project_root=tmp_path, section_mapper_fn=mapper)
    result = importer.import_text(source)
    # The actual header (line-start) was rewritten.
    assert result.rewritten_text.startswith("## Problem\n")
    # The prose mention retained its original form.
    assert "the '## The Problem We're Solving' section above" in result.rewritten_text
