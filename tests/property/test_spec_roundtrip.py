"""Random valid SpecDocument -> markdown -> parser -> equivalent SpecDocument."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ces.control.models.spec import (
    Risk,
    SignalHints,
    SpecDocument,
    SpecFrontmatter,
    Story,
)
from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader
from ces.harness.services.spec_authoring import render_markdown

_SAFE_TEXT = (
    # Sample directly from an ASCII-safe alphabet so `.strip()` and the
    # "no markdown-fence substrings" filter don't starve the generator:
    #   - letters/digits/space only (no newlines, no control chars)
    #   - excludes `**`, `::`, `-`, and backticks via the alphabet itself
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "),
        min_size=1,
        max_size=40,
    )
    .map(str.strip)
    .filter(bool)
)


@st.composite
def specs(draw):
    n_stories = draw(st.integers(min_value=1, max_value=4))
    story_ids = [f"ST-{i:04d}" for i in range(n_stories)]
    stories = []
    for i, sid in enumerate(story_ids):
        deps_pool = story_ids[:i]
        deps = (
            tuple(
                draw(
                    st.lists(
                        st.sampled_from(deps_pool),
                        max_size=min(2, len(deps_pool)),
                        unique=True,
                    )
                )
            )
            if deps_pool
            else ()
        )
        stories.append(
            Story(
                story_id=sid,
                title=draw(_SAFE_TEXT),
                description=draw(_SAFE_TEXT),
                acceptance_criteria=tuple(draw(st.lists(_SAFE_TEXT, min_size=1, max_size=3))),
                depends_on=deps,
                size=draw(st.sampled_from(["XS", "S", "M", "L"])),
                risk=draw(st.one_of(st.none(), st.sampled_from(["A", "B", "C"]))),
            )
        )
    return SpecDocument(
        frontmatter=SpecFrontmatter(
            spec_id="SP-PROP",
            title=draw(_SAFE_TEXT),
            owner="a@b.c",
            created_at=datetime(2026, 4, 21, tzinfo=timezone.utc),
            status="draft",
            signals=SignalHints(
                primary_change_class="feature",
                blast_radius_hint="isolated",
            ),
        ),
        problem=draw(_SAFE_TEXT),
        users=draw(_SAFE_TEXT),
        success_criteria=(draw(_SAFE_TEXT),),
        non_goals=(draw(_SAFE_TEXT),),
        risks=(Risk(risk=draw(_SAFE_TEXT), mitigation=draw(_SAFE_TEXT)),),
        stories=tuple(stories),
        rollback_plan=draw(_SAFE_TEXT),
    )


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(doc=specs())
def test_render_then_parse_preserves_story_ids_and_acceptance(tmp_path, doc):
    md = render_markdown(doc)
    parser = SpecParser(TemplateLoader(project_root=tmp_path))
    reparsed = parser.parse(md)
    assert [s.story_id for s in reparsed.stories] == [s.story_id for s in doc.stories]
    assert [s.acceptance_criteria for s in reparsed.stories] == [s.acceptance_criteria for s in doc.stories]
