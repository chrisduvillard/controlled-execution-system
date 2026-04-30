"""Tests for the ``ces spec`` subcommand group."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from ces.cli import app

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _patch_services(overrides: dict[str, Any]):
    """Return an asynccontextmanager factory that yields ``overrides``.

    Shape-matches the real :func:`ces.cli._factory.get_services` so the
    patched CLI code can ``async with`` it without caring about args.
    """

    @asynccontextmanager
    async def fake(*args: Any, **kwargs: Any):
        yield overrides

    return fake


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_spec_validate_accepts_valid_file(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))
    result = runner.invoke(app, ["spec", "validate", str(spec)])
    assert result.exit_code == 0, result.stdout
    assert "Ready for decompose" in result.stdout


def test_spec_validate_reports_missing_section(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "missing-non-goals.md").read_text(encoding="utf-8"))
    result = runner.invoke(app, ["spec", "validate", str(spec)])
    assert result.exit_code == 1
    assert "Non-Goals" in result.stdout


# ---------------------------------------------------------------------------
# decompose
# ---------------------------------------------------------------------------


def test_spec_decompose_persists_manifests(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    manager = MagicMock()
    manager.save_manifest = AsyncMock()
    manager.list_by_spec = AsyncMock(return_value=[])

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": audit}),
    ):
        result = runner.invoke(app, ["spec", "decompose", str(spec)])

    assert result.exit_code == 0, result.stdout
    assert "manifest stubs written" in result.stdout.lower()
    assert manager.save_manifest.await_count == 1
    audit.append_event.assert_awaited_once()


def test_spec_decompose_blocks_when_manifests_exist(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    existing = MagicMock()
    existing.manifest_id = "M-OLD"
    existing.parent_story_id = "ST-01HXY"

    manager = MagicMock()
    manager.save_manifest = AsyncMock()
    manager.list_by_spec = AsyncMock(return_value=[existing])

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": audit}),
    ):
        result = runner.invoke(app, ["spec", "decompose", str(spec)])

    assert result.exit_code == 1
    manager.save_manifest.assert_not_awaited()
    audit.append_event.assert_not_awaited()


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


def test_spec_reconcile_reports_added_and_orphans(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    existing_mf = MagicMock()
    existing_mf.parent_story_id = "ST-DELETED"
    existing_mf.manifest_id = "M-OLD"

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[existing_mf])

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": audit}),
    ):
        result = runner.invoke(app, ["spec", "reconcile", str(spec)])

    assert result.exit_code == 0, result.stdout
    assert "ST-DELETED" in result.stdout  # orphan
    assert "ST-01HXY" in result.stdout  # added (story in spec not yet decomposed)
    audit.append_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


def test_spec_tree_prints_hierarchy(runner: CliRunner, tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    mf = MagicMock()
    mf.manifest_id = "M-ABC"
    mf.parent_story_id = "ST-01HXY"
    mf.parent_spec_id = "SP-01HXY"
    mf.workflow_state = MagicMock(value="queued")

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])
    manager.get_manifest = AsyncMock(return_value=mf)

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["spec", "tree", str(spec)])

    assert result.exit_code == 0, result.stdout
    assert "SP-01HXY" in result.stdout
    assert "Add /healthcheck route" in result.stdout
    assert "queued" in result.stdout


# ---------------------------------------------------------------------------
# author
# ---------------------------------------------------------------------------


def test_spec_author_writes_markdown_to_docs_specs(runner: CliRunner, tmp_path: Path) -> None:
    # Full prompt transcript for the deterministic authoring interview.
    # Order must match SpecAuthoringEngine.run_interactive():
    #   _ask_frontmatter:
    #     title, owner, primary_change_class, blast_radius_hint,
    #     touches_data, touches_auth, touches_billing
    #   _ask_sections:
    #     problem, users,
    #     success_criteria (blank-terminated list),
    #     non_goals (blank-terminated list),
    #     risks (blank-terminated list of "risk :: mitigation"),
    #     rollback_plan
    #   _ask_stories:
    #     "Add a story?" -> if truthy: title, size, risk, depends_on,
    #     description, acceptance (blank-terminated list); repeat.
    #     "Add a story?" -> falsy: stop.
    inputs = (
        "Healthcheck\n"
        "dev@example.com\n"
        "feature\n"
        "isolated\n"
        "N\nN\nN\n"
        "Operators need a probe.\n"
        "Ops engineers.\n"
        "Route returns 200.\n\n"
        "No metrics.\n\n"
        "flaky :: retries\n\n"
        "Revert the PR.\n"
        "Y\n"
        "Add /healthcheck route\n"
        "S\n"
        "skip\n"
        "\n"
        "Wire HTTP route.\n"
        "Returns 200\n\n"
        "N\n"
    )

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services({"audit_ledger": audit}),
        ),
    ):
        result = runner.invoke(app, ["spec", "author"], input=inputs, catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    assert len(produced) == 1
    body = produced[0].read_text(encoding="utf-8")
    assert "## Problem" in body
    assert "Add /healthcheck route" in body
    audit.append_event.assert_awaited_once()


def test_spec_author_rejects_invalid_choice_instead_of_traceback(runner: CliRunner, tmp_path: Path) -> None:
    """Invalid primary_change_class should re-prompt (via click.Choice), not raise."""
    # Feed an invalid choice first, then a valid one, then normal answers.
    inputs = (
        "Healthcheck\n"
        "dev@example.com\n"
        "nonsense\n"
        "feature\n"
        "isolated\n"
        "N\nN\nN\n"
        "Operators need a probe.\n"
        "Ops engineers.\n"
        "Route returns 200.\n\n"
        "No metrics.\n\n"
        "flaky :: retries\n\n"
        "Revert the PR.\n"
        "Y\n"
        "Add route\n"
        "S\n"
        "skip\n"
        "\n"
        "Wire HTTP route.\n"
        "Returns 200\n\n"
        "N\n"
    )

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services({"audit_ledger": audit}),
        ),
    ):
        result = runner.invoke(app, ["spec", "author"], input=inputs, catch_exceptions=False)
    assert result.exit_code == 0, result.stdout
    # The file got created (spec was fully authored).
    assert list((tmp_path / "docs" / "specs").glob("*.md"))


# ---------------------------------------------------------------------------
# author --polish
# ---------------------------------------------------------------------------


def test_spec_author_polish_calls_provider_and_substitutes(runner: CliRunner, tmp_path: Path) -> None:
    """--polish rewrites long-form fields through the provider, bullets stay
    untouched, and at minimum problem+users+rollback+one story description
    are awaited (>= 4 provider calls)."""
    provider = MagicMock()
    llm_response = MagicMock()
    llm_response.content = "a much better description"
    provider.generate = AsyncMock(return_value=llm_response)
    registry = MagicMock()
    registry.get_provider.return_value = provider

    inputs = (
        "Healthcheck\n"
        "dev@example.com\n"
        "feature\n"
        "isolated\n"
        "N\nN\nN\n"
        "weak problem\n"
        "weak users\n"
        "Route returns 200.\n\n"
        "No metrics.\n\n"
        "flaky :: retries\n\n"
        "weak rollback\n"
        "Y\n"
        "Add route\n"
        "S\n"
        "skip\n"
        "\n"
        "weak story desc\n"
        "Returns 200\n\n"
        "N\n"
    )

    audit = MagicMock()
    audit.append_event = AsyncMock()
    kill_switch = MagicMock()
    kill_switch.is_halted = MagicMock(return_value=False)

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": kill_switch,
                    "audit_ledger": audit,
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "author", "--polish"], input=inputs, catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    assert len(produced) == 1
    body = produced[0].read_text(encoding="utf-8")
    # Polished content made it into the rendered markdown.
    assert "a much better description" in body
    # At minimum: problem + users + rollback_plan + one story description.
    assert provider.generate.await_count >= 4


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def test_spec_import_writes_rewritten_file_and_reports_missing(runner: CliRunner, tmp_path: Path) -> None:
    """Deterministic path: --no-llm skips the mapper, still rewrites what it
    can match verbatim and reports the rest as missing. Also asserts the
    import emits a distinct SPEC_IMPORTED audit event (distinct from
    SPEC_AUTHORED, which is reserved for specs written via ``spec author``)."""
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    audit = AsyncMock()

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services({"audit_ledger": audit}),
        ),
    ):
        result = runner.invoke(app, ["spec", "import", str(source), "--no-llm"], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    produced = list((tmp_path / "docs" / "specs").glob("*.md"))
    assert len(produced) == 1
    # The Notion export uses non-canonical headers, so Non-Goals is missing.
    assert "Non-Goals" in result.stdout
    # Audit event recorded.
    assert audit.append_event.await_count == 1
    call_args = audit.append_event.await_args
    # The distinct SPEC_IMPORTED event type lets downstream tooling
    # differentiate imported specs (which may have missing sections) from
    # freshly authored specs.
    from ces.shared.enums import EventType

    assert call_args.kwargs["event_type"] == EventType.SPEC_IMPORTED
    assert "Imported spec" in call_args.kwargs["action_summary"]


def test_spec_import_warns_on_llm_malformed_json(runner: CliRunner, tmp_path: Path) -> None:
    """When the LLM returns non-JSON, emit a user-facing warning instead of
    silently falling back (which would surface as every section marked
    missing with no explanation)."""
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    provider = MagicMock()
    bad_response = MagicMock()
    bad_response.content = "not json at all"
    provider.generate = AsyncMock(return_value=bad_response)
    registry = MagicMock()
    registry.get_provider.return_value = provider

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": MagicMock(is_halted=lambda: False),
                    "audit_ledger": AsyncMock(),
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "import", str(source)])
    assert result.exit_code == 0, result.stdout
    # Warning emitted.
    assert "unparseable" in result.stdout or "falling back" in result.stdout


def test_spec_validate_reports_cycle_as_validation_error(runner: CliRunner, tmp_path: Path) -> None:
    """Cyclic depends_on fails SpecValidator -- CLI must print the error and
    exit 1 rather than tracing out the ValidationError."""
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "cyclic-deps.md").read_text(encoding="utf-8"))
    result = runner.invoke(app, ["spec", "validate", str(spec)])
    assert result.exit_code == 1
    assert "Validation error" in result.stdout


def test_spec_decompose_rejects_invalid_spec(runner: CliRunner, tmp_path: Path) -> None:
    """Decompose must re-run the validator and exit on failure, not attempt
    to persist manifests for an invalid spec."""
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "cyclic-deps.md").read_text(encoding="utf-8"))

    manager = MagicMock()
    manager.save_manifest = AsyncMock()
    manager.list_by_spec = AsyncMock(return_value=[])

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": MagicMock()}),
    ):
        result = runner.invoke(app, ["spec", "decompose", str(spec)])

    assert result.exit_code == 1
    assert "Validation error" in result.stdout
    manager.save_manifest.assert_not_awaited()


def test_spec_reconcile_reports_unchanged_only(runner: CliRunner, tmp_path: Path) -> None:
    """When every spec story already has a manifest, reconcile prints the
    'Unchanged' branch (line 206)."""
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    # Match the story_id baked into minimal-valid.md so reconcile considers
    # the sole story unchanged.
    mf = MagicMock()
    mf.parent_story_id = "ST-01HXY"
    mf.manifest_id = "M-OK"

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[mf])

    audit = MagicMock()
    audit.append_event = AsyncMock()

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager, "audit_ledger": audit}),
    ):
        result = runner.invoke(app, ["spec", "reconcile", str(spec)])

    assert result.exit_code == 0, result.stdout
    assert "Unchanged" in result.stdout


def test_spec_tree_handles_story_without_manifest(runner: CliRunner, tmp_path: Path) -> None:
    """When a story has no manifest yet, tree must render the status-only
    branch (line 258) without crashing."""
    spec = tmp_path / "spec.md"
    spec.write_text((FIXTURES / "minimal-valid.md").read_text(encoding="utf-8"))

    manager = MagicMock()
    manager.list_by_spec = AsyncMock(return_value=[])  # no manifests exist
    manager.get_manifest = AsyncMock(return_value=None)

    with patch(
        "ces.cli.spec_cmd.get_services",
        new=_patch_services({"manifest_manager": manager}),
    ):
        result = runner.invoke(app, ["spec", "tree", str(spec)])

    assert result.exit_code == 0, result.stdout
    assert "SP-01HXY" in result.stdout
    assert "Add /healthcheck route" in result.stdout


def test_slugify_falls_back_to_spec_for_pure_separators() -> None:
    """_slugify must return 'spec' when the title contains nothing but
    separators (line 277 fallback)."""
    from ces.cli.spec_cmd import _slugify

    assert _slugify("---") == "spec"
    assert _slugify("   ") == "spec"


def test_spec_author_polish_recovers_from_provider_exception(runner: CliRunner, tmp_path: Path) -> None:
    """When provider.generate raises, polish must fall back to the draft
    (lines 395-396) and still emit the spec."""
    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("boom"))
    registry = MagicMock()
    registry.get_provider.return_value = provider

    inputs = (
        "Healthcheck\n"
        "dev@example.com\n"
        "feature\n"
        "isolated\n"
        "N\nN\nN\n"
        "a problem\n"
        "some users\n"
        "Route returns 200.\n\n"
        "No metrics.\n\n"
        "flaky :: retries\n\n"
        "Revert the PR.\n"
        "Y\n"
        "Add route\n"
        "S\n"
        "skip\n"
        "\n"
        "Wire HTTP route.\n"
        "Returns 200\n\n"
        "N\n"
    )

    audit = MagicMock()
    audit.append_event = AsyncMock()
    kill_switch = MagicMock(is_halted=MagicMock(return_value=False))

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": kill_switch,
                    "audit_ledger": audit,
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "author", "--polish"], input=inputs, catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    body = next((tmp_path / "docs" / "specs").glob("*.md")).read_text()
    # Draft preserved because polish errored.
    assert "a problem" in body


def test_spec_author_polish_skipped_when_kill_switch_halted(runner: CliRunner, tmp_path: Path) -> None:
    """Kill switch engaged -> never call the provider (guards the
    `halted` branch on line 345)."""
    provider = MagicMock()
    provider.generate = AsyncMock()
    registry = MagicMock()
    registry.get_provider.return_value = provider

    inputs = (
        "Healthcheck\n"
        "dev@example.com\n"
        "feature\n"
        "isolated\n"
        "N\nN\nN\n"
        "some problem\n"
        "some users\n"
        "Route returns 200.\n\n"
        "No metrics.\n\n"
        "flaky :: retries\n\n"
        "Revert the PR.\n"
        "N\n"
    )

    audit = MagicMock()
    audit.append_event = AsyncMock()
    kill_switch = MagicMock(is_halted=MagicMock(return_value=True))

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": kill_switch,
                    "audit_ledger": audit,
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "author", "--polish"], input=inputs, catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    # Kill switch halted -> provider.generate must never be awaited.
    provider.generate.assert_not_awaited()


def test_spec_import_warns_on_llm_provider_exception(runner: CliRunner, tmp_path: Path) -> None:
    """Provider raises during section mapping -> importer warns and falls
    back to exact-match (lines 460-465)."""
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    provider = MagicMock()
    provider.generate = AsyncMock(side_effect=RuntimeError("net down"))
    registry = MagicMock()
    registry.get_provider.return_value = provider

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": MagicMock(is_halted=lambda: False),
                    "audit_ledger": AsyncMock(),
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "import", str(source)])

    assert result.exit_code == 0, result.stdout
    assert "failed" in result.stdout or "falling back" in result.stdout


def test_spec_import_warns_on_llm_unexpected_shape(runner: CliRunner, tmp_path: Path) -> None:
    """LLM returns a JSON array instead of an object -> importer warns on
    the shape and falls back (lines 475-479)."""
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    provider = MagicMock()
    bad = MagicMock()
    bad.content = '["not", "a", "dict"]'  # valid JSON, wrong shape
    provider.generate = AsyncMock(return_value=bad)
    registry = MagicMock()
    registry.get_provider.return_value = provider

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": MagicMock(is_halted=lambda: False),
                    "audit_ledger": AsyncMock(),
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "import", str(source)])

    assert result.exit_code == 0, result.stdout
    assert "unexpected shape" in result.stdout or "falling back" in result.stdout


def test_spec_import_uses_llm_mapper_by_default(runner: CliRunner, tmp_path: Path) -> None:
    """Default path: invokes provider.generate exactly once up-front; the
    mapping is passed through a closure so SpecImporter stays sync."""
    source = tmp_path / "src.md"
    source.write_text((FIXTURES / "notion-export.md").read_text(encoding="utf-8"))

    provider = MagicMock()
    llm_response = MagicMock()
    llm_response.content = (
        '{"## Problem": "## The Problem We\'re Solving", '
        '"## Users": "## Who It\'s For", '
        '"## Success Criteria": "## What Success Looks Like", '
        '"## Rollback Plan": "## Rolling Back", '
        '"## Stories": "## User Stories"}'
    )
    provider.generate = AsyncMock(return_value=llm_response)
    registry = MagicMock()
    registry.get_provider.return_value = provider

    audit = MagicMock()
    audit.append_event = AsyncMock()
    kill_switch = MagicMock()
    kill_switch.is_halted = MagicMock(return_value=False)

    with (
        patch("ces.cli.spec_cmd._project_root", return_value=tmp_path),
        patch(
            "ces.cli.spec_cmd.get_services",
            new=_patch_services(
                {
                    "provider_registry": registry,
                    "kill_switch": kill_switch,
                    "audit_ledger": audit,
                }
            ),
        ),
    ):
        result = runner.invoke(app, ["spec", "import", str(source)], catch_exceptions=False)

    assert result.exit_code == 0, result.stdout
    # Provider called exactly once for the mapping.
    assert provider.generate.await_count == 1
    # With the LLM mapping Problem/Users/Success/Rollback/Stories are found,
    # so only Non-Goals and Risks remain missing.
    assert "Missing sections" in result.stdout
    assert "## Non-Goals" in result.stdout
