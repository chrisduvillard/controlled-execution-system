from pathlib import Path

from ces.harness.services.spec_authoring import SpecAuthoringEngine


def _scripted_prompt(responses):
    it = iter(responses)

    def prompt(text, *, default=None, choices=None, type=None):  # noqa: A002
        return next(it)

    return prompt


def test_author_produces_spec_document_from_scripted_answers(tmp_path: Path):
    engine = SpecAuthoringEngine(
        project_root=tmp_path,
        prompt_fn=_scripted_prompt(
            [
                # frontmatter
                "Healthcheck",  # title
                "dev@example.com",  # owner
                "feature",  # primary_change_class
                "isolated",  # blast_radius_hint
                "N",  # touches_data
                "N",  # touches_auth
                "N",  # touches_billing
                # sections
                "Operators need a probe.",  # problem
                "Ops engineers.",  # users
                "Route returns 200.",  # success_criteria line 1
                "",  # success_criteria done
                "No metrics.",  # non_goals line 1
                "",  # non_goals done
                "flaky :: retries",  # risks line 1
                "",  # risks done
                "Revert the PR.",  # rollback_plan
                # one story
                "Y",  # add a story?
                "Add /healthcheck route",  # story.title
                "S",  # size
                "skip",  # risk (skip)
                "",  # depends_on (none)
                "Wire HTTP route.",  # description
                "Returns 200",  # acceptance line 1
                "",  # acceptance done
                "N",  # add another story?
            ]
        ),
    )
    doc = engine.run_interactive()
    assert doc.frontmatter.title == "Healthcheck"
    assert len(doc.stories) == 1
    assert doc.stories[0].acceptance_criteria == ("Returns 200",)
    assert doc.stories[0].risk is None  # "skip" maps to None
    # IDs generated via uuid
    assert doc.frontmatter.spec_id.startswith("SP-")
    assert doc.stories[0].story_id.startswith("ST-")


def test_polish_fn_transforms_authored_fields(tmp_path: Path):
    """When polish_fn is supplied, _maybe_polish runs the transform on each authored field."""
    polished_calls: list[tuple[str, str]] = []

    def polish(field: str, draft: str) -> str:
        polished_calls.append((field, draft))
        return draft.upper()

    engine = SpecAuthoringEngine(
        project_root=tmp_path,
        polish_fn=polish,
        prompt_fn=_scripted_prompt(
            [
                "Healthcheck",
                "dev@example.com",
                "feature",
                "isolated",
                "N",
                "N",
                "N",
                "Operators need a probe.",
                "Ops engineers.",
                "Route returns 200.",
                "",
                "No metrics.",
                "",
                "flaky :: retries",
                "",
                "Revert the PR.",
                "N",  # no stories
            ]
        ),
    )
    doc = engine.run_interactive()
    # The polish hook ran -- at least one field was transformed.
    assert polished_calls, "polish_fn was never invoked"
    # And the polish actually mutated content (uppercase) somewhere visible.
    assert doc.problem == "OPERATORS NEED A PROBE." or doc.users == "OPS ENGINEERS."


def test_render_markdown_round_trips_through_parser(tmp_path):
    from ces.control.spec.parser import SpecParser
    from ces.control.spec.template_loader import TemplateLoader
    from ces.harness.services.spec_authoring import render_markdown

    engine = SpecAuthoringEngine(
        project_root=tmp_path,
        prompt_fn=_scripted_prompt(
            [
                "Healthcheck",
                "dev@example.com",
                "feature",
                "isolated",
                "N",
                "N",
                "N",
                "p",
                "u",
                "s1",
                "",
                "n1",
                "",
                "r :: m",
                "",
                "rb",
                "Y",
                "Add route",
                "S",
                "C",
                "",
                "desc",
                "a1",
                "",
                "N",
            ]
        ),
    )
    doc = engine.run_interactive()

    md = render_markdown(doc)
    parser = SpecParser(TemplateLoader(project_root=tmp_path))
    reparsed = parser.parse(md)
    assert reparsed.frontmatter.title == doc.frontmatter.title
    assert reparsed.stories[0].story_id == doc.stories[0].story_id
    assert reparsed.stories[0].acceptance_criteria == doc.stories[0].acceptance_criteria
