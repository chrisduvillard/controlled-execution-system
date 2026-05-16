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
    commands: list[VerificationCommand] = []
    if project_type.startswith("python"):
        commands.extend(_python_commands(project_root, project_type))
    elif project_type in {"node-app", "vite-react-app"}:
        commands.extend(_node_commands(project_root))
    commands.extend(_subproject_commands(project_root, acceptance_criteria, start_index=len(commands)))
    commands.extend(_criterion_commands(acceptance_criteria, project_root))
    return tuple(commands)


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
    package_manager = _node_package_manager(project_root, payload)
    commands: list[VerificationCommand] = []
    for name, kind in (("test", "test"), ("typecheck", "typecheck"), ("build", "build"), ("lint", "lint")):
        if isinstance(scripts, dict) and name in scripts:
            commands.append(
                VerificationCommand(
                    id=_command_id(commands), kind=kind, command=_node_run_command(package_manager, name)
                )
            )
    return tuple(commands)


def _node_package_manager(project_root: Path, package_json: dict[str, Any]) -> str:
    declared = str(package_json.get("packageManager", "")).strip().casefold()
    if declared.startswith("bun@") or (project_root / "bun.lock").is_file() or (project_root / "bun.lockb").is_file():
        return "bun"
    if declared.startswith("pnpm@") or (project_root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if declared.startswith("yarn@") or (project_root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _node_run_command(package_manager: str, script_name: str) -> str:
    if package_manager == "npm" and script_name == "test":
        return "npm test"
    return f"{package_manager} run {script_name}"


def _node_install_command(project_root: Path) -> str:
    package_manager = _node_package_manager(project_root, _read_json(project_root / "package.json"))
    if package_manager == "bun":
        return "bun install --frozen-lockfile"
    if package_manager == "pnpm":
        return "pnpm install --frozen-lockfile"
    if package_manager == "yarn":
        return "yarn install --frozen-lockfile"
    return "npm ci"


def _subproject_commands(
    project_root: Path,
    acceptance_criteria: tuple[str, ...] | list[str],
    *,
    start_index: int,
) -> tuple[VerificationCommand, ...]:
    """Infer validation commands for nested projects explicitly named by the task."""
    commands: list[VerificationCommand] = []
    for rel_path in _mentioned_project_paths(acceptance_criteria):
        subproject = project_root / rel_path
        if not (subproject / "package.json").is_file():
            continue
        node_commands = _node_commands(subproject)
        if not node_commands:
            continue
        commands.append(
            VerificationCommand(
                id=f"VC-{start_index + len(commands) + 1:03d}",
                kind="install",
                command=_node_install_command(subproject),
                cwd=rel_path,
                timeout_seconds=300,
            )
        )
        for command in node_commands:
            commands.append(
                VerificationCommand(
                    id=f"VC-{start_index + len(commands) + 1:03d}",
                    kind=command.kind,
                    command=command.command,
                    cwd=rel_path,
                    timeout_seconds=command.timeout_seconds,
                    expected_exit_codes=command.expected_exit_codes,
                )
            )
    return tuple(commands)


def _mentioned_project_paths(criteria: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    paths: list[str] = []
    for criterion in criteria:
        for match in re.finditer(r"(?:^|\s)([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)/?", str(criterion)):
            path = match.group(1).strip("`.,:;()[]{}")
            if path and path not in paths:
                paths.append(path)
    return tuple(paths)


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
