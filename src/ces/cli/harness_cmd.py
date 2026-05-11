"""Implementation of the conservative `ces harness` command group."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.table import Table

from ces.cli._output import console
from ces.execution.secrets import scrub_secrets_from_text
from ces.harness_evolution.attribution import compute_change_verdict
from ces.harness_evolution.distiller import distill_transcript_file
from ces.harness_evolution.manifest_io import read_manifest
from ces.harness_evolution.memory import draft_lesson_from_trajectory, sanitize_lesson_text
from ces.harness_evolution.paths import HarnessPaths, create_harness_layout, relative_layout_entries
from ces.harness_evolution.repository import HarnessEvolutionRepository
from ces.harness_evolution.verdicts import read_trajectory_report
from ces.local_store import LocalProjectStore

harness_app = typer.Typer(
    help="Inspect and initialize local harness evolution artifacts.",
    rich_markup_mode="rich",
)
changes_app = typer.Typer(
    help="Validate local harness change manifests.",
    rich_markup_mode="rich",
)
memory_app = typer.Typer(
    help="Draft, activate, and inspect evidence-backed harness memory lessons.",
    rich_markup_mode="rich",
)


def _project_root(project_root: Path | None = None) -> Path:
    return (project_root or Path.cwd()).resolve()


def _project_root_option() -> Path | None:
    return typer.Option(
        None,
        "--project-root",
        help="Repo/CES project root to inspect; defaults to the current working directory.",
    )


def _repository(root: Path) -> HarnessEvolutionRepository:
    return HarnessEvolutionRepository(LocalProjectStore(root / ".ces" / "state.db", project_id="default"))


@harness_app.callback(invoke_without_command=True)
def harness_root(ctx: typer.Context) -> None:
    """Show help when no harness subcommand is provided."""

    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit


@harness_app.command(name="init")
def init_harness(
    project_root: Path | None = _project_root_option(),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show the intended `.ces/harness/` layout without writing files.",
    ),
) -> None:
    """Initialize the local `.ces/harness/` substrate."""

    root = _project_root(project_root)
    entries = relative_layout_entries(root)
    if dry_run:
        console.print("Harness init dry-run: would ensure these local paths:")
        for entry in entries:
            console.print(f"- {entry}")
        console.print("No files were written. Runtime prompt injection remains disabled.")
        return

    paths = create_harness_layout(root)
    console.print(f"Initialized local harness substrate at {paths.root.relative_to(root)}")
    console.print("Created/ensured:")
    for entry in entries:
        console.print(f"- {entry}")
    console.print("Runtime prompt injection remains disabled.")


@harness_app.command(name="inspect")
def inspect_harness(project_root: Path | None = _project_root_option()) -> None:
    """Inspect whether the local harness substrate is initialized."""

    root = _project_root(project_root)
    paths = HarnessPaths.for_project(root)
    if not paths.index.exists():
        console.print("Harness substrate is not initialized.")
        console.print("Next action: run `ces harness init --dry-run`, then `ces harness init`.")
        raise typer.Exit(code=1)

    table = Table(title="Harness substrate")
    table.add_column("Path")
    table.add_column("Status")
    for entry in relative_layout_entries(root):
        path = root / entry.rstrip("/")
        table.add_row(entry, "present" if path.exists() else "missing")
    console.print(table)
    console.print("Runtime prompt injection: disabled")


@harness_app.command(name="analyze")
def analyze_transcript(
    from_transcript: Path = typer.Option(
        ...,
        "--from-transcript",
        help="Raw runtime/dogfood transcript to distill into a compact harness trajectory report.",
    ),
    json_output: Path | None = typer.Option(None, "--json-output", help="Write structured JSON report here."),
    markdown_output: Path | None = typer.Option(None, "--markdown-output", help="Write markdown report here."),
) -> None:
    """Distill a transcript into structured JSON and markdown reports."""

    try:
        report = distill_transcript_file(from_transcript)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Could not analyze transcript: {safe_error}")
        raise typer.Exit(code=1) from exc

    json_text = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    markdown_text = report.to_markdown()
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json_text, encoding="utf-8")
        console.print(f"wrote JSON: {json_output}")
    else:
        console.print(json_text.rstrip())
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(markdown_text, encoding="utf-8")
        console.print(f"wrote markdown: {markdown_output}")
    else:
        console.print(markdown_text.rstrip())


@harness_app.command(name="verdict")
def compute_verdict(
    change_id: str,
    from_analysis: Path = typer.Option(
        ...,
        "--from-analysis",
        help="Structured JSON trajectory report produced by `ces harness analyze`.",
    ),
    project_root: Path | None = _project_root_option(),
) -> None:
    """Compute and persist a regression-aware verdict for a harness change."""

    root = _project_root(project_root)
    repo = _repository(root)
    change = repo.get_change(change_id)
    if change is None:
        console.print(f"Harness change not found: {change_id}")
        raise typer.Exit(code=1)

    try:
        analysis = read_trajectory_report(from_analysis)
        verdict = compute_change_verdict(change.manifest, analysis)
        record = repo.save_verdict(verdict)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Could not compute harness verdict: {safe_error}")
        raise typer.Exit(code=1) from exc

    console.print(f"saved harness verdict: {record.id}")
    console.print(f"change id: {record.change_id}")
    console.print(f"verdict: {record.verdict}")
    console.print(f"predicted fixes observed: {len(verdict.observed_fixes)}")
    console.print(f"predicted fixes missed: {len(verdict.missed_fixes)}")
    console.print(f"predicted regressions observed: {len(verdict.observed_predicted_regressions)}")
    console.print(f"unexpected regressions: {len(verdict.unexpected_regressions)}")
    console.print(f"rationale: {verdict.rationale}")


@changes_app.command(name="validate")
def validate_change_manifest(manifest_path: Path) -> None:
    """Validate a harness change manifest without persisting it."""

    try:
        manifest = read_manifest(manifest_path)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Invalid harness change manifest: {safe_error}")
        raise typer.Exit(code=1) from exc

    console.print(f"Valid harness change manifest: {manifest.change_id}")
    console.print(f"component: {manifest.component_type.value}")
    console.print(f"predicted fixes: {len(manifest.predicted_fixes)}")
    console.print(f"predicted regressions: {len(manifest.predicted_regressions)}")


@changes_app.command(name="add")
def add_change_manifest(
    manifest_path: Path,
    project_root: Path | None = _project_root_option(),
) -> None:
    """Validate and persist a harness change manifest in `.ces/state.db`."""

    root = _project_root(project_root)
    try:
        manifest = read_manifest(manifest_path)
        record = _repository(root).save_change(manifest)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Could not save harness change manifest: {safe_error}")
        raise typer.Exit(code=1) from exc

    console.print(f"saved harness change: {record.change_id}")
    console.print(f"status: {record.status}")
    console.print(f"manifest hash: {record.manifest_hash}")


@changes_app.command(name="list")
def list_changes(
    project_root: Path | None = _project_root_option(),
    status: str | None = typer.Option(None, "--status", help="Filter by harness change status."),
) -> None:
    """List persisted harness change manifests."""

    records = _repository(_project_root(project_root)).list_changes(status=status)
    if not records:
        console.print("No harness changes found.")
        return

    console.print("Harness changes:")
    for record in records:
        console.print(
            f"- {record.change_id} | component={record.component_type} | "
            f"status={record.status} | title={record.title} | updated={record.updated_at}"
        )


@changes_app.command(name="show")
def show_change(
    change_id: str,
    project_root: Path | None = _project_root_option(),
) -> None:
    """Show a persisted harness change manifest summary."""

    record = _repository(_project_root(project_root)).get_change(change_id)
    if record is None:
        console.print(f"Harness change not found: {change_id}")
        raise typer.Exit(code=1)

    manifest = record.manifest
    console.print(f"change id: {record.change_id}")
    console.print(f"title: {record.title}")
    console.print(f"component: {record.component_type}")
    console.print(f"status: {record.status}")
    console.print(f"manifest hash: {record.manifest_hash}")
    console.print(f"predicted fixes: {len(manifest.predicted_fixes)}")
    console.print(f"predicted regressions: {len(manifest.predicted_regressions)}")
    console.print(f"validation steps: {len(manifest.validation_plan)}")
    verdicts = _repository(_project_root(project_root)).list_verdicts(change_id)
    if verdicts:
        console.print(f"latest verdict: {verdicts[-1].verdict}")


@memory_app.command(name="draft")
def draft_memory_lesson(
    from_analysis: Path = typer.Option(
        ...,
        "--from-analysis",
        help="Structured JSON trajectory report produced by `ces harness analyze`.",
    ),
    project_root: Path | None = _project_root_option(),
) -> None:
    """Draft a local harness memory lesson from trajectory evidence."""

    root = _project_root(project_root)
    try:
        analysis = read_trajectory_report(from_analysis)
        lesson = draft_lesson_from_trajectory(analysis)
        record = _repository(root).save_memory_lesson(lesson)
    except (OSError, ValueError, ValidationError) as exc:
        safe_error = scrub_secrets_from_text(str(exc))
        console.print(f"Could not draft harness memory lesson: {safe_error}")
        raise typer.Exit(code=1) from exc

    console.print(f"saved harness memory lesson: {record.lesson_id}")
    console.print(f"lesson id: {record.lesson_id}")
    console.print(f"status: {record.status}")
    console.print(f"content hash: {record.content_hash}")


@memory_app.command(name="activate")
def activate_memory_lesson(
    lesson_id: str,
    project_root: Path | None = _project_root_option(),
) -> None:
    """Activate a reviewed harness memory lesson for future builder runs."""

    root = _project_root(project_root)
    record = _repository(root).activate_memory_lesson(lesson_id)
    if record is None:
        console.print(f"Harness memory lesson not found: {lesson_id}")
        raise typer.Exit(code=1)
    console.print(f"activated harness memory lesson: {record.lesson_id}")
    console.print(f"status: {record.status}")
    console.print(f"content hash: {record.content_hash}")


@memory_app.command(name="archive")
def archive_memory_lesson(
    lesson_id: str,
    project_root: Path | None = _project_root_option(),
) -> None:
    """Archive a harness memory lesson so it is no longer injected at runtime."""

    root = _project_root(project_root)
    record = _repository(root).archive_memory_lesson(lesson_id)
    if record is None:
        console.print(f"Harness memory lesson not found: {lesson_id}")
        raise typer.Exit(code=1)
    console.print(f"archived harness memory lesson: {record.lesson_id}")
    console.print(f"status: {record.status}")
    console.print(f"content hash: {record.content_hash}")


@memory_app.command(name="list")
def list_memory_lessons(
    project_root: Path | None = _project_root_option(),
    status: str | None = typer.Option(None, "--status", help="Filter by lesson status: draft, active, archived."),
) -> None:
    """List persisted harness memory lessons."""

    root = _project_root(project_root)
    records = _repository(root).list_memory_lessons(status=status)
    if not records:
        console.print("No harness memory lessons found.")
        return
    console.print("Harness memory lessons:")
    for record in records:
        safe_title = sanitize_lesson_text(record.title)
        console.print(
            f"- {record.lesson_id} | kind={record.kind} | status={record.status} | "
            f"title={safe_title} | content hash={record.content_hash}"
        )


harness_app.add_typer(changes_app, name="changes")
harness_app.add_typer(memory_app, name="memory")
