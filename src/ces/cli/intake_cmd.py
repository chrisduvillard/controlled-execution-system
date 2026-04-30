"""Implementation of the ``ces intake`` command.

Runs an interactive Q&A intake interview loop for a phase. Questions are
displayed one at a time via Rich panels. Answers are collected via
typer.prompt(). Stage progression follows: mandatory -> conditional ->
completeness -> completed.

Uses IntakeInterviewEngine from the intake subsystem.

Exports:
    run_intake: Typer command function for ``ces intake``.
"""

from __future__ import annotations

import json

import typer
from rich.panel import Panel
from rich.table import Table

import ces.cli._output as _output_mod
from ces.cli._async import run_async
from ces.cli._context import find_project_root, get_project_id
from ces.cli._errors import handle_error
from ces.cli._factory import get_services
from ces.cli._output import console


@run_async
async def run_intake(
    phase: int = typer.Argument(
        ...,
        help="Phase number (1-3)",
    ),
) -> None:
    """Start an interactive intake interview for the given phase.

    Displays questions one at a time and collects answers via prompt.
    Progresses through mandatory, conditional, and completeness stages.
    Shows session summary at the end.
    """
    try:
        find_project_root()
        project_id = get_project_id()

        async with get_services() as services:
            engine = services["intake_engine"]
            project_id = "default"

            # Start session
            session_id = await engine.start_session(phase, project_id)

            if not _output_mod._json_mode:
                console.print(f"[bold]Intake session started:[/bold] {session_id}")
                console.print(f"Phase: {phase}\n")

            # Q&A loop
            while True:
                question = await engine.get_next_question(session_id)

                if question is None:
                    # No more questions in current stage -- try advancing
                    try:
                        new_stage = await engine.advance_stage(session_id)
                        if new_stage == "completed":
                            break
                        if not _output_mod._json_mode:
                            console.print(f"\n[dim]Stage advanced to: {new_stage}[/dim]\n")
                        continue
                    except (ValueError, Exception):
                        break

                if not _output_mod._json_mode:
                    # Display question in Rich panel
                    console.print(
                        Panel(
                            question.text,
                            title=f"Question {question.question_id}",
                            border_style="cyan",
                        )
                    )

                # Collect answer
                answer_text = typer.prompt("Your answer")

                await engine.submit_answer(
                    session_id,
                    question.question_id,
                    answer_text=answer_text,
                    answered_by="cli-user",
                )

            # Display session summary
            status = await engine.get_session_status(session_id)

            if _output_mod._json_mode:
                typer.echo(json.dumps(status, indent=2, default=str))
                return

            # Rich table summary
            table = Table(title="Intake Session Summary")
            table.add_column("Field")
            table.add_column("Value")
            table.add_row("Session ID", session_id)
            table.add_row("Stage", status["current_stage"])
            table.add_row("Answered", str(status["answered_count"]))
            table.add_row("Total Questions", str(status["total_questions"]))
            if status.get("blocked_questions"):
                table.add_row(
                    "Blocked",
                    ", ".join(status["blocked_questions"]),
                )
            console.print(table)

    except (typer.BadParameter, ValueError) as exc:
        handle_error(exc)
    except (ConnectionError, RuntimeError, OSError) as exc:
        handle_error(exc)
    except Exception as exc:
        handle_error(exc)
