"""Tests for verification command inference."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path


def test_infers_python_cli_commands(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='promptvault'\ndependencies=['pytest']\n[project.scripts]\npromptvault='promptvault.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "promptvault").mkdir(parents=True)
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-cli")

    assert [command.kind for command in commands] == ["test", "compile", "smoke"]
    python = shlex.quote(sys.executable)
    assert commands[0].command == f"{python} -m pytest -q"
    assert commands[1].command == f"{python} -m compileall src tests"
    assert commands[2].command == f"{python} -c \"import sys; sys.path.insert(0, 'src'); import promptvault.cli\""


def test_prefers_uv_run_when_lockfile_exists(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\ndependencies=['pytest']\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-package")

    assert commands[0].command == "uv run python -m pytest -q"


def test_prefers_project_local_venv_python_when_present(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\ndependencies=['pytest']\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    venv_python.chmod(0o755)

    commands = infer_verification_commands(tmp_path, "python-package")

    assert commands[0].command == ".venv/bin/python -m pytest -q"


def test_does_not_infer_pytest_from_tests_directory_alone(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    commands = infer_verification_commands(tmp_path, "python-package")

    assert all("pytest" not in command.command for command in commands)
    assert [command.kind for command in commands] == ["compile"]


def test_infers_pytest_from_requirements_file(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest>=8\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-package")

    assert commands[0].command == f"{shlex.quote(sys.executable)} -m pytest -q"


def test_infers_pytest_from_tox_config(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[testenv]\ndeps = pytest\ncommands = pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    commands = infer_verification_commands(tmp_path, "python-package")

    assert commands[0].command == f"{shlex.quote(sys.executable)} -m pytest -q"


def test_infers_node_package_commands(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}),
        encoding="utf-8",
    )

    commands = infer_verification_commands(tmp_path, "vite-react-app")

    assert [command.command for command in commands] == ["npm test", "npm run build"]


def test_infers_bun_node_package_commands_when_bun_lock_exists(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "bun test", "build": "bun build ./src/index.ts"}}),
        encoding="utf-8",
    )
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    commands = infer_verification_commands(tmp_path, "node-app")

    assert [command.command for command in commands] == ["bun run test", "bun run build"]


def test_infers_node_subproject_commands_from_acceptance_paths(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='ces'\ndependencies=['pytest']\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    app = tmp_path / "examples" / "voice-to-text-mvp"
    app.mkdir(parents=True)
    (app / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "test": "vitest",
                    "typecheck": "tsc --noEmit",
                    "build": "vite build",
                    "lint": "eslint .",
                }
            }
        ),
        encoding="utf-8",
    )

    commands = infer_verification_commands(
        tmp_path,
        "python-package",
        acceptance_criteria=(
            "examples/voice-to-text-mvp contains a working local voice-to-text MVP",
            "Automated validation exists and passes locally",
        ),
    )

    subproject_commands = [command for command in commands if command.cwd == "examples/voice-to-text-mvp"]
    assert [command.kind for command in subproject_commands] == ["install", "test", "typecheck", "build", "lint"]
    assert [command.command for command in subproject_commands] == [
        "npm ci",
        "npm test",
        "npm run typecheck",
        "npm run build",
        "npm run lint",
    ]


def test_infers_bun_subproject_install_and_commands_from_acceptance_paths(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='ces'\ndependencies=['pytest']\n", encoding="utf-8")
    app = tmp_path / "examples" / "gstack-like-app"
    app.mkdir(parents=True)
    (app / "bun.lock").write_text("", encoding="utf-8")
    (app / "package.json").write_text(
        json.dumps({"scripts": {"test": "bun test", "build": "bun build ./src/index.ts"}}),
        encoding="utf-8",
    )

    commands = infer_verification_commands(
        tmp_path,
        "python-package",
        acceptance_criteria=("examples/gstack-like-app preserves the existing Bun workflow",),
    )

    subproject_commands = [command for command in commands if command.cwd == "examples/gstack-like-app"]
    assert [command.kind for command in subproject_commands] == ["install", "test", "build"]
    assert [command.command for command in subproject_commands] == [
        "bun install --frozen-lockfile",
        "bun run test",
        "bun run build",
    ]


def test_infers_uv_cli_smoke_command_when_lockfile_exists(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='promptvault'\ndependencies=['pytest']\n[project.scripts]\npromptvault='promptvault.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    commands = infer_verification_commands(tmp_path, "python-cli")

    assert commands[-1].command == "uv run promptvault --help"


def test_infers_expected_failure_commands_from_explicit_negative_acceptance(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='releasepulse'\n[project.scripts]\nreleasepulse='releasepulse.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    commands = infer_verification_commands(
        tmp_path,
        "python-cli",
        acceptance_criteria=("`uv run releasepulse check missing.md` exits non-zero with a helpful message",),
    )

    negative_commands = [command for command in commands if command.kind == "negative-smoke"]
    assert len(negative_commands) == 1
    assert negative_commands[0].command == "uv run releasepulse check missing.md"
    assert negative_commands[0].expected_exit_codes == (1,)


def test_rewrites_negative_python_commands_to_project_invocation(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    commands = infer_verification_commands(
        tmp_path,
        "python-package",
        acceptance_criteria=("`python -m demo missing.txt` exits non-zero with a helpful message",),
    )

    negative_commands = [command for command in commands if command.kind == "negative-smoke"]
    assert len(negative_commands) == 1
    assert negative_commands[0].command == f"{shlex.quote(sys.executable)} -m demo missing.txt"


def test_preserves_uv_prefix_for_negative_script_commands(tmp_path: Path) -> None:
    from ces.verification.command_inference import infer_verification_commands

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n[project.scripts]\ndemo='demo.cli:app'\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    commands = infer_verification_commands(
        tmp_path,
        "python-cli",
        acceptance_criteria=("`demo missing.txt` exits non-zero with a helpful message",),
    )

    negative_commands = [command for command in commands if command.kind == "negative-smoke"]
    assert len(negative_commands) == 1
    assert negative_commands[0].command == "uv run demo missing.txt"
