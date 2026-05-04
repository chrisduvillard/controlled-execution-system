"""Tests for verification command inference."""

from __future__ import annotations

import json
from pathlib import Path


def test_infers_python_cli_commands(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='promptvault'\n[project.scripts]\npromptvault='promptvault.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "promptvault").mkdir(parents=True)
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-cli")

    assert [command.kind for command in commands] == ["test", "compile", "smoke"]
    assert commands[0].command == "python -m pytest -q"
    assert commands[1].command == "python -m compileall src tests"
    assert commands[2].command == "python -c \"import sys; sys.path.insert(0, 'src'); import promptvault.cli\""


def test_prefers_uv_run_when_lockfile_exists(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-package")

    assert commands[0].command == "uv run python -m pytest -q"


def test_infers_node_package_commands(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}),
        encoding="utf-8",
    )

    commands = infer_verification_commands(tmp_path, "vite-react-app")

    assert [command.command for command in commands] == ["npm test", "npm run build"]


def test_infers_uv_cli_smoke_command_when_lockfile_exists(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='promptvault'\n[project.scripts]\npromptvault='promptvault.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    commands = infer_verification_commands(tmp_path, "python-cli")

    assert commands[-1].command == "uv run promptvault --help"
