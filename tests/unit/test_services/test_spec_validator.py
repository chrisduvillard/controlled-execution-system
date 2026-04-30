from pathlib import Path

import pytest

from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.validator import SpecValidationError, SpecValidator

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def validator(tmp_path: Path) -> SpecValidator:
    loader = TemplateLoader(project_root=tmp_path)
    return SpecValidator(loader)


@pytest.fixture
def parser(tmp_path: Path) -> SpecParser:
    return SpecParser(TemplateLoader(project_root=tmp_path))


def test_validates_minimal_spec(validator: SpecValidator, parser: SpecParser):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    doc = parser.parse(text)
    validator.validate(doc, template_name="default")  # does not raise


def test_detects_dependency_cycle(validator: SpecValidator, parser: SpecParser):
    text = (FIXTURES / "cyclic-deps.md").read_text(encoding="utf-8")
    doc = parser.parse(text)
    with pytest.raises(SpecValidationError, match="cycle"):
        validator.validate(doc, template_name="default")


def test_detects_unknown_depends_on(validator: SpecValidator, parser: SpecParser):
    text = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    bad = text.replace("- **depends_on:** []", "- **depends_on:** [ST-ZZZ]")
    doc = parser.parse(bad)
    with pytest.raises(SpecValidationError, match="unknown"):
        validator.validate(doc, template_name="default")


def test_empty_acceptance_criteria_rejected(validator: SpecValidator):
    """A story with no acceptance criteria fails the structural check."""
    from ces.control.models.spec import Story
    from ces.control.spec.template_loader import TemplateSidecar

    sidecar = TemplateSidecar(
        name="default",
        version=1,
        required_sections=(),
        story_header_pattern="^### Story:",
        required_story_fields=(),
    )
    story = Story(
        story_id="ST-EMPTY",
        title="No criteria",
        description="Acceptance list is empty.",
        acceptance_criteria=(),
        size="S",
    )
    with pytest.raises(SpecValidationError, match="no acceptance criteria"):
        validator._check_story_fields((story,), sidecar)


def test_diamond_dependency_graph_is_acyclic(validator: SpecValidator):
    """A diamond graph (A->C, B->C) hits the visited-node early return without raising.

    After A's traversal marks C visited, B's traversal reaches C and must
    short-circuit on the `if node in visited: return` branch instead of
    re-walking it.
    """
    from ces.control.models.spec import Story

    common = Story(
        story_id="ST-C",
        title="C",
        description="",
        acceptance_criteria=("ok",),
        depends_on=(),
        size="S",
    )
    left = Story(
        story_id="ST-A",
        title="A",
        description="",
        acceptance_criteria=("ok",),
        depends_on=("ST-C",),
        size="S",
    )
    right = Story(
        story_id="ST-B",
        title="B",
        description="",
        acceptance_criteria=("ok",),
        depends_on=("ST-C",),
        size="S",
    )
    # Order matters: left walks ST-C first, marking it visited; right re-encounters it.
    validator._check_dependency_graph_acyclic((left, right, common))
