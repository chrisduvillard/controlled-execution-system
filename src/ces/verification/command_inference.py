"""Infer local verification commands from project files."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from ces.verification.completion_contract import VerificationCommand

NEGATIVE_EXIT_MARKERS = (
    "nonzero",
    "non-zero",
    "non zero",
    "exit 1",
    "exits 1",
    "exit code 1",
    "fails with",
    "should fail",
)


def infer_verification_commands(
    project_root: Path,
    project_type: str,
    acceptance_criteria: tuple[str, ...] | list[str] = (),
) -> tuple[VerificationCommand, ...]:
    if project_type.startswith("python"):
        return (*_python_commands(project_root, project_type), *_criterion_commands(acceptance_criteria, project_root))
    if project_type in {"node-app", "vite-react-app"}:
        return (*_node_commands(project_root), *_criterion_commands(acceptance_criteria, project_root))
    return ()


def _python_commands(project_root: Path, project_type: str) -> tuple[VerificationCommand, ...]:
    prefix = "uv run " if (project_root / "uv.lock").is_file() else ""
    commands: list[VerificationCommand] = []
    if (project_root / "tests").is_dir():
        commands.append(
            VerificationCommand(id=_command_id(commands), kind="test", command=f"{prefix}python -m pytest -q")
        )
    compile_targets = [target for target in ("src", "tests") if (project_root / target).exists()]
    if compile_targets:
        commands.append(
            VerificationCommand(
                id=_command_id(commands),
                kind="compile",
                command=f"{prefix}python -m compileall {' '.join(compile_targets)}",
            )
        )
    if project_type == "python-cli":
        script = _first_project_script(project_root)
        script_module = _first_project_script_module(project_root)
        if script and prefix:
            commands.append(
                VerificationCommand(id=_command_id(commands), kind="smoke", command=f"{prefix}{script} --help")
            )
        elif script_module:
            commands.append(
                VerificationCommand(
                    id=_command_id(commands),
                    kind="smoke",
                    command=f"python -c \"import sys; sys.path.insert(0, 'src'); import {script_module}\"",
                )
            )
    return tuple(commands)


def _node_commands(project_root: Path) -> tuple[VerificationCommand, ...]:
    payload = _read_json(project_root / "package.json")
    scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
    commands: list[VerificationCommand] = []
    for name, kind in (("test", "test"), ("lint", "lint"), ("build", "build")):
        if isinstance(scripts, dict) and name in scripts:
            commands.append(
                VerificationCommand(
                    id=_command_id(commands), kind=kind, command=f"npm {'test' if name == 'test' else f'run {name}'}"
                )
            )
    return tuple(commands)


def _first_project_script(project_root: Path) -> str | None:
    payload = _read_toml(project_root / "pyproject.toml")
    project = payload.get("project", {}) if isinstance(payload, dict) else {}
    scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
    if isinstance(scripts, dict) and scripts:
        return str(next(iter(scripts)))
    return None


def _first_project_script_module(project_root: Path) -> str | None:
    payload = _read_toml(project_root / "pyproject.toml")
    project = payload.get("project", {}) if isinstance(payload, dict) else {}
    scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
    if not isinstance(scripts, dict) or not scripts:
        return None
    entrypoint = str(next(iter(scripts.values())))
    module = entrypoint.split(":", 1)[0].strip()
    return module or None


def _command_id(commands: list[VerificationCommand]) -> str:
    return f"VC-{len(commands) + 1:03d}"


def _criterion_commands(criteria: tuple[str, ...] | list[str], project_root: Path) -> tuple[VerificationCommand, ...]:
    commands: list[VerificationCommand] = []
    prefix = "uv run " if (project_root / "uv.lock").is_file() else ""
    for criterion in criteria:
        text = str(criterion).strip()
        if not _expects_failure(text):
            continue
        command = _extract_backticked_command(text)
        if command is None:
            continue
        if prefix and _first_project_script(project_root) and not command.startswith("uv run "):
            command = f"{prefix}{command}"
        commands.append(
            VerificationCommand(
                id=f"VC-criterion-negative-{len(commands) + 1:03d}",
                kind="negative-smoke",
                command=command,
                expected_exit_codes=(1,),
            )
        )
    return tuple(commands)


def _expects_failure(text: str) -> bool:
    normalized = text.casefold()
    return any(marker in normalized for marker in NEGATIVE_EXIT_MARKERS)


def _extract_backticked_command(text: str) -> str | None:
    match = re.search(r"`([^`]+)`", text)
    if match is None:
        return None
    command = match.group(1).strip()
    return command or None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
