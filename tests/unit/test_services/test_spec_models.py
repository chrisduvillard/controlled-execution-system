"""Unit tests for ces spec authoring Pydantic models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ces.control.models.spec import Risk, SignalHints, SpecDocument, SpecFrontmatter, Story


def test_signal_hints_enforces_literals():
    sh = SignalHints(
        primary_change_class="feature",
        blast_radius_hint="isolated",
    )
    assert sh.touches_data is False
    assert sh.touches_auth is False


def test_signal_hints_rejects_invalid_change_class():
    with pytest.raises(ValidationError):
        SignalHints(primary_change_class="nonsense", blast_radius_hint="isolated")


def test_risk_requires_both_fields():
    r = Risk(risk="flaky network", mitigation="add retries")
    assert r.risk == "flaky network"
    assert r.mitigation == "add retries"
    with pytest.raises(ValidationError):
        Risk(risk="flaky network")  # missing mitigation
    with pytest.raises(ValidationError):
        Risk(mitigation="add retries")  # missing risk


def test_spec_frontmatter_is_frozen():
    fm = SpecFrontmatter(
        spec_id="SP-01",
        title="Healthcheck",
        owner="dev@example.com",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        status="draft",
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
        ),
    )
    with pytest.raises(ValidationError):
        fm.title = "X"  # frozen


def _minimal_frontmatter():
    return SpecFrontmatter(
        spec_id="SP-01",
        title="T",
        owner="a@b.c",
        created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
        status="draft",
        signals=SignalHints(
            primary_change_class="feature",
            blast_radius_hint="isolated",
        ),
    )


def test_story_requires_acceptance_criteria_as_tuple():
    story = Story(
        story_id="ST-01",
        title="Add healthcheck",
        description="Wire HTTP route.",
        acceptance_criteria=("returns 200",),
        size="S",
    )
    assert isinstance(story.acceptance_criteria, tuple)
    assert story.depends_on == ()
    assert story.risk is None


def test_story_rejects_list_under_strict_mode():
    with pytest.raises(ValidationError):
        Story(
            story_id="ST-01",
            title="x",
            description="x",
            acceptance_criteria=["a"],  # list, not tuple -- strict mode rejects
            size="S",
        )


def test_specdocument_composes_full_spec():
    doc = SpecDocument(
        frontmatter=_minimal_frontmatter(),
        problem="Operators can't probe liveness.",
        users="Ops engineers.",
        success_criteria=("Route returns 200.",),
        non_goals=("No metrics in this change.",),
        risks=(Risk(risk="r", mitigation="m"),),
        stories=(
            Story(
                story_id="ST-01",
                title="Add route",
                description="desc",
                acceptance_criteria=("criterion",),
                size="S",
            ),
        ),
        rollback_plan="Revert the PR.",
    )
    assert len(doc.stories) == 1
    assert doc.frontmatter.spec_id == "SP-01"
