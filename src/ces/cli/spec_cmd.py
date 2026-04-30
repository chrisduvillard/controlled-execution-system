"""Implementation of the ``ces spec`` subcommand group.

Exposes the spec-authoring lifecycle at the CLI:

* ``ces spec validate``  -- deterministic template + structure validation.
* ``ces spec decompose`` -- expand a spec into manifest stubs.
* ``ces spec reconcile`` -- diff a spec against existing manifests.
* ``ces spec tree``      -- render the spec/story/manifest hierarchy.
* ``ces spec author``    -- interactive spec authoring wizard.
* ``ces spec import``    -- rewrite an existing PRD to the canonical template.

All commands are deterministic (LLM-05 compliant) except the optional
``--polish`` flag on ``spec author`` (wired up in a later phase) and the
default LLM section mapper on ``spec import`` (fleshed out in a follow-up).
Both LLM paths honor the kill switch and degrade to a deterministic flow.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import typer
from rich.console import Console
from rich.tree import Tree

from ces.cli._async import run_async
from ces.cli._factory import get_services
from ces.control.models.audit_entry import AuditScope
from ces.control.models.spec import SpecDocument
from ces.control.spec.decomposer import SpecDecomposer
from ces.control.spec.parser import SpecParseError, SpecParser
from ces.control.spec.reconciler import SpecReconciler
from ces.control.spec.template_loader import TemplateLoader
from ces.control.spec.tree import SpecTree
from ces.control.spec.validator import SpecValidationError, SpecValidator
from ces.harness.services.spec_authoring import (
    SpecAuthoringEngine,
    render_markdown,
)
from ces.harness.services.spec_importer import SpecImporter
from ces.shared.enums import ActorType, EventType

# Model id used for LLM-assisted section mapping and `--polish`.
# Resolved via the provider registry's longest-prefix match against the
# "claude" prefix registered by :func:`register_cli_fallback`.
_POLISH_MODEL_ID = "claude-sonnet-4-6"

spec_app = typer.Typer(
    help="Spec lifecycle: author, validate, decompose, reconcile, tree.",
    no_args_is_help=True,
)
_console = Console()


def _project_root() -> Path:
    """Return the project root (cwd).

    Extracted into a small helper so tests can monkeypatch it without
    needing to chdir.
    """
    return Path.cwd()


def _parse_spec(spec_path: Path, loader: TemplateLoader) -> Any:
    """Parse a spec file, converting parse errors into CLI-friendly exits."""
    parser = SpecParser(loader)
    try:
        return parser.parse(spec_path.read_text(encoding="utf-8"))
    except SpecParseError as exc:
        _console.print(f"[red]Parse error:[/red] {exc}")
        raise typer.Exit(code=1) from None


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@spec_app.command("validate")
def spec_validate(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Validate a spec file against its template."""
    loader = TemplateLoader(_project_root())
    doc = _parse_spec(spec_path, loader)
    validator = SpecValidator(loader)
    try:
        validator.validate(doc, template_name=doc.frontmatter.template)
    except SpecValidationError as exc:
        _console.print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    _console.print(f"[green]OK[/green] {doc.frontmatter.spec_id} -- {len(doc.stories)} stories. Ready for decompose.")


# ---------------------------------------------------------------------------
# decompose
# ---------------------------------------------------------------------------


@spec_app.command("decompose")
@run_async
async def spec_decompose(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Decompose even when manifests already exist for this spec "
            "(prior manifests are retained; duplicates must be cleaned "
            "up manually)."
        ),
    ),
) -> None:
    """Decompose a validated spec into manifest stubs."""
    loader = TemplateLoader(_project_root())
    doc = _parse_spec(spec_path, loader)
    validator = SpecValidator(loader)
    try:
        validator.validate(doc, template_name=doc.frontmatter.template)
    except SpecValidationError as exc:
        _console.print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    async with get_services() as services:
        manager = services["manifest_manager"]
        existing = await manager.list_by_spec(doc.frontmatter.spec_id)
        if existing and not force:
            _console.print(
                f"[red]Error:[/red] spec {doc.frontmatter.spec_id} already "
                f"has {len(existing)} manifest(s). Use --force or "
                f"`ces spec reconcile`."
            )
            raise typer.Exit(code=1)

        decomposer = SpecDecomposer(loader)
        result = decomposer.decompose(doc)
        for manifest in result.manifests:
            await manager.save_manifest(manifest)

        audit = services.get("audit_ledger")
        await audit.append_event(
            event_type=EventType.SPEC_DECOMPOSED,
            actor=doc.frontmatter.owner,
            actor_type=ActorType.HUMAN,
            action_summary=(f"Decomposed spec {doc.frontmatter.spec_id} into {len(result.manifests)} manifest(s)"),
            scope=AuditScope(affected_manifests=tuple(m.manifest_id for m in result.manifests)),
        )

    _console.print(f"[green]OK[/green] {len(result.manifests)} manifest stubs written.")


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------


@spec_app.command("reconcile")
@run_async
async def spec_reconcile(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Report added/orphaned/unchanged stories vs. existing manifests."""
    loader = TemplateLoader(_project_root())
    doc = _parse_spec(spec_path, loader)

    async with get_services() as services:
        manager = services["manifest_manager"]
        manifests = await manager.list_by_spec(doc.frontmatter.spec_id)
        existing_story_ids = frozenset(m.parent_story_id for m in manifests if m.parent_story_id)

        reconciler = SpecReconciler(loader)
        report = reconciler.reconcile(doc, existing_story_ids)

        if report.added:
            _console.print(f"[yellow]Added:[/yellow] {', '.join(report.added)}")
        if report.orphaned:
            _console.print(f"[red]Orphaned (manifests exist but story deleted):[/red] {', '.join(report.orphaned)}")
            _console.print(
                "Orphaned manifests are kept for human review. Use `ces manifest delete <M-...>` if truly obsolete."
            )
        if report.unchanged:
            _console.print(f"[green]Unchanged:[/green] {', '.join(report.unchanged)}")
        if not (report.added or report.orphaned or report.unchanged):
            _console.print(
                f"[green]OK[/green] spec {doc.frontmatter.spec_id} has no stories and no existing manifests."
            )

        audit = services.get("audit_ledger")
        await audit.append_event(
            event_type=EventType.SPEC_RECONCILED,
            actor=doc.frontmatter.owner,
            actor_type=ActorType.HUMAN,
            action_summary=(
                f"Reconciled spec {doc.frontmatter.spec_id}: "
                f"{len(report.added)} added, "
                f"{len(report.orphaned)} orphaned, "
                f"{len(report.unchanged)} unchanged"
            ),
        )


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


@spec_app.command("tree")
@run_async
async def spec_tree(
    spec_path: Path = typer.Argument(..., exists=True, readable=True),
) -> None:
    """Render the spec -> stories -> manifest-status hierarchy."""
    loader = TemplateLoader(_project_root())
    doc = _parse_spec(spec_path, loader)

    async with get_services() as services:
        tree_service = SpecTree(services["manifest_manager"])
        nodes = await tree_service.render(doc)

    root = Tree(f"[bold]{doc.frontmatter.spec_id}[/bold] {doc.frontmatter.title} ({doc.frontmatter.status})")
    for node in nodes:
        if node.manifest_id:
            label = f"{node.story_id} {node.story_title} [{node.manifest_id} {node.status_label}]"
        else:
            label = f"{node.story_id} {node.story_title} [{node.status_label}]"
        root.add(label)
    _console.print(root)


# ---------------------------------------------------------------------------
# author
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Collapse a spec title to a filename-safe slug."""
    cleaned = [c if c.isalnum() or c in {"-", "_"} else "-" for c in title.lower()]
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "spec"


@spec_app.command("author")
@run_async
async def spec_author(
    template: str = typer.Option("default", "--template", help="Template name to drive the interview."),
    polish: bool = typer.Option(
        False,
        "--polish",
        help=(
            "Run long-form answers (problem, users, rollback plan, and each "
            "story description) through an LLM for clarity. Best-effort: "
            "falls back to the draft on provider failure or kill switch."
        ),
    ),
) -> None:
    """Interactively author a new spec and persist it under docs/specs/."""
    root = _project_root()

    def prompt(
        text: str,
        *,
        choices: list[str] | None = None,
        default: Any = None,
        value_type: Any = None,
    ) -> str:
        del value_type
        if choices:
            # When a closed set of choices is required, defer to
            # click.Choice so invalid/empty input re-prompts instead of
            # flowing into pydantic and raising ValidationError.
            prompt_text = f"{text} [{'|'.join(choices)}]"
            return str(
                typer.prompt(
                    prompt_text,
                    type=click.Choice(list(choices), case_sensitive=False),
                    show_choices=False,
                )
            )
        # Free-text prompts default to "" so blank input is accepted:
        # the authoring engine signals "end of list" via an empty
        # response and typer.prompt otherwise re-prompts on empty.
        effective_default = default if default is not None else ""
        return str(
            typer.prompt(
                text,
                default=effective_default,
                show_default=default is not None,
            )
        )

    # Phase 1: synchronous interview (user I/O stays on the main thread).
    engine = SpecAuthoringEngine(
        project_root=root,
        prompt_fn=prompt,
        polish_fn=None,
    )
    doc = engine.run_interactive()

    async with get_services() as services:
        # Phase 2: optional LLM polish (async). Skipped silently when no
        # provider is available or the kill switch is engaged.
        if polish:
            registry = services.get("provider_registry")
            kill_switch = services.get("kill_switch")
            halted = kill_switch.is_halted() if kill_switch is not None else False
            if registry is not None and not halted:
                doc = await _polish_spec_document(registry, doc, kill_switch=kill_switch)

        # Phase 3: write to disk + audit.
        out_dir = root / "docs" / "specs"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(doc.frontmatter.title)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = out_dir / f"{today}-{slug}.md"
        out_path.write_text(render_markdown(doc), encoding="utf-8")

        audit = services.get("audit_ledger")
        await audit.append_event(
            event_type=EventType.SPEC_AUTHORED,
            actor=doc.frontmatter.owner,
            actor_type=ActorType.HUMAN,
            action_summary=(
                f"Authored spec {doc.frontmatter.spec_id} ({len(doc.stories)} stories) with template {template}"
            ),
        )

    _console.print(f"[green]Wrote[/green] {out_path}")


async def _polish_spec_document(registry: Any, doc: SpecDocument, kill_switch: Any = None) -> SpecDocument:
    """Return a copy of ``doc`` with long-form fields rewritten by an LLM.

    Bullet lists (success_criteria, non_goals, acceptance_criteria) are
    intentionally left untouched -- they are already short and structured.
    Polish is best-effort: any failure falls back to the original draft.

    A kill-switch halt between individual field polishes is honoured: the
    remaining fields fall back to their drafts instead of dispatching more
    LLM calls. Before 0.1.2 the halt was only checked at the outer call
    site, so a halt during polishing would be ignored by subsequent calls.
    """
    provider = registry.get_provider(_POLISH_MODEL_ID)

    async def polish_field(field_name: str, draft: str) -> str:
        if not draft.strip():
            return draft
        if kill_switch is not None and kill_switch.is_halted():
            return draft
        messages = [
            {
                "role": "user",
                "content": (
                    "Rewrite this spec field for clarity and specificity in "
                    "1-3 sentences. Preserve the author's meaning; do not "
                    "introduce new requirements.\n\n"
                    f"Field: {field_name}\nDraft:\n{draft}"
                ),
            }
        ]
        try:
            response = await provider.generate(_POLISH_MODEL_ID, messages)
        except Exception:
            return draft
        content = getattr(response, "content", None)
        if not isinstance(content, str) or not content.strip():
            return draft
        return content.strip()

    new_problem = await polish_field("problem", doc.problem)
    new_users = await polish_field("users", doc.users)
    new_rollback = await polish_field("rollback_plan", doc.rollback_plan)

    polished_stories = []
    for story in doc.stories:
        new_description = await polish_field("story.description", story.description)
        polished_stories.append(story.model_copy(update={"description": new_description}))

    return doc.model_copy(
        update={
            "problem": new_problem,
            "users": new_users,
            "rollback_plan": new_rollback,
            "stories": tuple(polished_stories),
        }
    )


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


async def _llm_section_mapping(
    registry: Any,
    source: str,
    project_root: Path,
    kill_switch: Any = None,
) -> dict[str, str]:
    """Ask the LLM to map the source doc's headers to canonical template headers.

    Returns a dict of canonical->source. Returns an empty dict on any
    failure (provider error, malformed JSON, unexpected shape, or kill
    switch halt). The caller passes this dict verbatim to
    :class:`SpecImporter` via a closure; the importer intersects it with
    the actual headers present in the source, so a spurious entry from
    the model cannot forge a match.
    """
    loader = TemplateLoader(project_root)
    sidecar = loader.load("default")
    required = sidecar.required_sections
    provider = registry.get_provider(_POLISH_MODEL_ID)
    if kill_switch is not None and kill_switch.is_halted():
        return {}
    messages = [
        {
            "role": "user",
            "content": (
                "You are mapping sections in a source document to canonical "
                "headers. Return ONLY a JSON object whose keys are canonical "
                "headers and values are the matching source headers (or null "
                "if no match).\n\n"
                f"Canonical headers: {list(required)}\n\n"
                f"Source document:\n{source}"
            ),
        }
    ]
    try:
        response = await provider.generate(_POLISH_MODEL_ID, messages)
    except Exception:
        _console.print(
            "[yellow]Warning:[/yellow] LLM section mapping provider call failed; falling back to exact-match only."
        )
        return {}
    try:
        data = json.loads(response.content)
    except (json.JSONDecodeError, AttributeError, TypeError):
        _console.print(
            "[yellow]Warning:[/yellow] LLM section mapping returned unparseable JSON; falling back to exact-match only."
        )
        return {}
    if not isinstance(data, dict):
        _console.print(
            "[yellow]Warning:[/yellow] LLM section mapping returned unexpected shape; falling back to exact-match only."
        )
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


@spec_app.command("import")
@run_async
async def spec_import(
    source_path: Path = typer.Argument(..., exists=True, readable=True),
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help=(
            "Skip LLM section mapping; only match canonical headers "
            "verbatim. Useful when the input already uses canonical "
            "headers or when you need a fully deterministic import."
        ),
    ),
) -> None:
    """Import an existing PRD; map its headers to the canonical template.

    Writes the rewritten markdown to ``docs/specs/<name>.imported.md`` and
    reports any required sections that could not be mapped, so the author
    can fill them in manually or via ``ces spec author``.
    """
    root = _project_root()
    source = source_path.read_text(encoding="utf-8")

    async with get_services() as services:
        mapper = None
        if not no_llm:
            registry = services.get("provider_registry")
            kill_switch = services.get("kill_switch")
            halted = kill_switch.is_halted() if kill_switch is not None else False
            if registry is not None and not halted:
                # Resolve the mapping ONCE here (async) and pass a closure
                # to the importer so SpecImporter.map_sections stays sync.
                precomputed = await _llm_section_mapping(registry, source, root, kill_switch=kill_switch)

                def mapper(_src: object, _req: object) -> object:
                    return precomputed

        importer = SpecImporter(project_root=root, section_mapper_fn=mapper)
        result = importer.import_text(source)

        out_dir = root / "docs" / "specs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{source_path.stem}.imported.md"
        out_path.write_text(result.rewritten_text, encoding="utf-8")

        audit = services.get("audit_ledger")
        if audit is not None:
            await audit.append_event(
                event_type=EventType.SPEC_IMPORTED,
                actor=str(source_path),  # best-effort; source doc has no explicit owner
                actor_type=ActorType.HUMAN,
                action_summary=f"Imported spec from {source_path.name} -> {out_path.name}",
            )

    _console.print(f"[green]Wrote[/green] {out_path}")
    if result.mapping.missing:
        _console.print(
            "[yellow]Missing sections (add them interactively or "
            f"manually):[/yellow] {', '.join(result.mapping.missing)}"
        )
