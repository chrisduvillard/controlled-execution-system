from pathlib import Path

import pytest

from ces.control.models.spec import SpecDocument
from ces.control.spec.parser import SpecParseError, SpecParser
from ces.control.spec.template_loader import TemplateLoader

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


@pytest.fixture
def parser(loader: TemplateLoader) -> SpecParser:
    return SpecParser(loader)


def test_parses_minimal_valid_spec(parser: SpecParser):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    doc = parser.parse(text, template_name="default")
    assert isinstance(doc, SpecDocument)
    assert doc.frontmatter.spec_id == "SP-01HXY"
    assert doc.problem.strip() == "Operators need a probe."
    assert doc.success_criteria == ("Route returns 200.",)
    assert len(doc.stories) == 1


def test_rejects_missing_frontmatter(parser: SpecParser):
    with pytest.raises(SpecParseError, match="frontmatter"):
        parser.parse("## Problem\nFoo\n", template_name="default")


def test_missing_required_section_raises(parser: SpecParser):
    text = (FIXTURES / "missing-non-goals.md").read_text(encoding="utf-8")
    with pytest.raises(SpecParseError, match="Non-Goals"):
        parser.parse(text, template_name="default")


def test_story_without_id_raises(parser: SpecParser, tmp_path: Path):
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    mangled = base.replace("- **id:** ST-01HXY\n", "")  # drop id line
    with pytest.raises((SpecParseError, ValueError)):
        parser.parse(mangled, template_name="default")


def test_blank_line_terminates_acceptance_block(parser: SpecParser):
    """A blank line between acceptance bullets and the next field must not
    swallow the next field into the acceptance list."""
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    # Insert a blank line after the first acceptance bullet by replacing the
    # - **acceptance: block. The resulting story still has valid fields; what
    # we're checking is that parsing doesn't treat `- **description:` or
    # `- **size:` as acceptance lines after the blank.
    mangled = base.replace(
        "- **acceptance:**\n  - Returns 200 with JSON body\n  - p95 under 50ms\n",
        "- **acceptance:**\n  - Returns 200 with JSON body\n\n  - p95 under 50ms\n",
    )
    doc = parser.parse(mangled, template_name="default")
    # The second acceptance bullet is separated by a blank line, so under the
    # fixed semantics it should NOT be part of acceptance_criteria.
    assert doc.stories[0].acceptance_criteria == ("Returns 200 with JSON body",)


def test_story_missing_size_raises_spec_parse_error(parser: SpecParser):
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    mangled = base.replace("- **size:** S\n", "")
    with pytest.raises(SpecParseError, match="size"):
        parser.parse(mangled, template_name="default")


def test_story_missing_description_raises_spec_parse_error(parser: SpecParser):
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    mangled = base.replace("- **description:** Wire HTTP route.\n", "")
    with pytest.raises(SpecParseError, match="description"):
        parser.parse(mangled, template_name="default")


def test_invalid_yaml_frontmatter_raises_spec_parse_error(parser: SpecParser):
    """Malformed YAML in the frontmatter block surfaces as SpecParseError."""
    text = "---\nspec_id: [unterminated\ntitle: x\n---\n## Problem\nFoo\n"
    with pytest.raises(SpecParseError, match="not valid YAML"):
        parser.parse(text, template_name="default")


def test_empty_risk_value_is_skipped(parser: SpecParser):
    """A story with an empty risk value (`- **risk:**` with no value) skips the field
    rather than assigning the empty string. Story.risk defaults to None.
    """
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    mangled = base.replace("- **risk:** C\n", "- **risk:**\n")
    doc = parser.parse(mangled, template_name="default")
    assert doc.stories[0].risk is None
