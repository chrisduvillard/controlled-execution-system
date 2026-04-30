"""Project-scan + Rich-panel helpers backing the guided ``ces build`` wizard.

Extracted from ``run_cmd.py`` to keep that module focused on the Typer
entry-points and the brief-flow orchestrator. All helpers here are pure:
they read the filesystem or render Rich primitives and have no
dependency on the resolved service graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from ces.cli._output import console

WIZARD_STEPS = 5
"""Number of steps in the guided interactive wizard."""


@dataclass(frozen=True)
class ProjectDefaults:
    """Smart defaults derived from project filesystem scan."""

    project_mode: str  # "brownfield" or "greenfield"
    has_pytest: bool  # pyproject.toml [tool.pytest] or pytest.ini or conftest.py
    has_ci: bool  # .github/workflows/ directory exists with .yml files
    has_coverage_data: bool  # coverage.json or .coverage file exists
    manifest_count: int  # count of .ces/manifests/ entries
    suggested_risk_tier: str  # "B" default


def pyproject_has_pytest(project_root: Path) -> bool:
    """Check if pyproject.toml contains [tool.pytest.ini_options]."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
        return "[tool.pytest.ini_options]" in content or "[tool.pytest]" in content
    except (OSError, UnicodeDecodeError):
        return False


def scan_project_defaults(project_root: Path) -> ProjectDefaults:
    """Scan project filesystem for smart defaults. Must complete in <2 seconds."""
    skip_names = {".ces", ".git", ".hg", "__pycache__", ".venv", "node_modules"}
    has_repo_files = any(
        p.name not in skip_names
        for p in project_root.iterdir()
        if p.is_file() or (p.is_dir() and p.name not in skip_names)
    )
    project_mode = "brownfield" if has_repo_files else "greenfield"

    has_pytest = (
        (project_root / "pytest.ini").exists()
        or (project_root / "conftest.py").exists()
        or pyproject_has_pytest(project_root)
    )

    workflows_dir = project_root / ".github" / "workflows"
    has_ci = workflows_dir.is_dir() and any(workflows_dir.glob("*.yml"))

    has_coverage = (project_root / "coverage.json").exists() or (project_root / ".coverage").exists()

    ces_manifests = project_root / ".ces" / "manifests"
    manifest_count = len(list(ces_manifests.glob("*.yaml"))) if ces_manifests.is_dir() else 0

    return ProjectDefaults(
        project_mode=project_mode,
        has_pytest=has_pytest,
        has_ci=has_ci,
        has_coverage_data=has_coverage,
        manifest_count=manifest_count,
        suggested_risk_tier="B",
    )


def wizard_step_panel(
    step: int,
    total: int,
    title: str,
    content: str,
    help_text: str | None = None,
) -> None:
    """Render a wizard step as a Rich Panel with step indicator."""
    console.print(
        Panel(
            content,
            title=f"[cyan]Step {step}/{total}[/cyan] {title}",
            border_style="cyan",
        )
    )
    if help_text:
        console.print(f"  [dim]{help_text}[/dim]")


def build_confirmation_table(
    *,
    risk_tier: str,
    affected_files_count: int,
    acceptance_criteria: list[str],
    runtime: str,
    brownfield_count: int,
    governance: bool,
) -> Table:
    """Build a Rich Table summarizing wizard-collected values for confirmation."""
    table = Table(title="Confirmation Summary", show_lines=True)
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Risk Tier", risk_tier)
    table.add_row("Affected Files", str(affected_files_count))
    table.add_row(
        "Acceptance Criteria",
        ", ".join(acceptance_criteria) if acceptance_criteria else "(none)",
    )
    table.add_row("Runtime", runtime)
    table.add_row("Brownfield Items", str(brownfield_count))
    table.add_row("Governance", "enabled" if governance else "standard")
    return table


def format_scan_results(defaults: ProjectDefaults) -> str:
    """Format project scan results for the Step 1 panel."""
    lines = [
        f"Project mode: {defaults.project_mode}",
        f"Pytest detected: {'yes' if defaults.has_pytest else 'no'}",
        f"CI detected: {'yes' if defaults.has_ci else 'no'}",
        f"Coverage data: {'yes' if defaults.has_coverage_data else 'no'}",
        f"Existing manifests: {defaults.manifest_count}",
        f"Suggested risk tier: {defaults.suggested_risk_tier}",
    ]
    return "\n".join(lines)
