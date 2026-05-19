"""CLI tests for Production Autopilot commands."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _write_minimal_project(root: Path) -> None:
    (root / "README.md").write_text("# Demo\nSafety invariant: never print secret values.\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        """
[project]
name = "demo"
dependencies = ["pytest", "ruff"]

[tool.pytest.ini_options]
addopts = "-q"

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")


def _snapshot_files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_next_json_reports_next_safe_action(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["next", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["current_maturity"] == "shareable-app"
    assert payload["target_maturity"] == "production-candidate"
    assert payload["recommended_command"]
    assert "feature_work_guidance" in payload


def test_next_prompt_markdown_contains_agent_guardrails(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["next-prompt", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "# CES Developer Intent Contract" in result.stdout
    assert "Scope Drift Kill Switch" in result.stdout
    assert "Exact `ces:completion` expectations" in result.stdout


def test_next_prompt_json_accepts_objective_acceptance_and_must_not_break(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        [
            "next-prompt",
            "Add invoice notes",
            "--project-root",
            str(tmp_path),
            "--acceptance",
            "Notes render in export output.",
            "--must-not-break",
            "Existing export rows stay intact.",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["original_objective"] == "Add invoice notes"
    assert payload["acceptance_criteria"] == ["Notes render in export output."]
    assert "Existing export rows stay intact." in payload["must_not_break"]
    assert payload["contract_status"] == "implementation-ready"


def test_next_prompt_json_blocks_high_risk_objective_without_acceptance(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        ["next-prompt", "Rotate production database credentials", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["contract_status"] == "blocked"
    assert payload["intent_gate"]["decision"] == "blocked"


def test_next_prompt_cli_is_read_only(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(),
        ["next-prompt", "Add invoice notes", "--project-root", str(tmp_path), "--format", "json"],
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (tmp_path / ".ces").exists()


def test_deliberate_markdown_outputs_approach_decision_brief(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["deliberate", "Add invoice notes", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "# Approach Decision Brief" in result.stdout
    assert "## Alternatives" in result.stdout
    assert "## Independent perspectives" in result.stdout
    assert "## Preserved dissent" in result.stdout
    assert "## Recommended synthesis" in result.stdout
    assert "## Blockers" in result.stdout
    assert "## Next CES command" in result.stdout
    assert "read-only" in result.stdout
    assert "does not launch Codex or Claude Code" in result.stdout


def test_deliberate_help_lists_command_and_options_work(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    root_help = runner.invoke(_get_app(), ["--help"])
    command_help = runner.invoke(_get_app(), ["deliberate", "--help"])
    command_result = runner.invoke(
        _get_app(),
        [
            "deliberate",
            "Add invoice notes",
            "--project-root",
            str(tmp_path),
            "--acceptance",
            "Notes render in export output.",
            "--must-not-break",
            "Existing export rows stay intact.",
            "--format",
            "json",
        ],
    )

    assert root_help.exit_code == 0, root_help.stdout
    assert command_help.exit_code == 0, command_help.stdout
    assert command_result.exit_code == 0, command_result.stdout
    assert "deliberate" in root_help.stdout


def test_deliberate_json_shape_and_read_only(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    before = _snapshot_files(tmp_path)

    result = runner.invoke(
        _get_app(),
        [
            "deliberate",
            "Add invoice notes",
            "--project-root",
            str(tmp_path),
            "--acceptance",
            "Notes render in export output.",
            "--must-not-break",
            "Existing export rows stay intact.",
            "--format",
            "json",
        ],
    )

    after = _snapshot_files(tmp_path)
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (tmp_path / ".ces").exists()
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["objective"] == "Add invoice notes"
    assert payload["execution_mode"] == "read-only-deliberation"
    assert len(payload["alternatives"]) >= 2
    assert {item["role"] for item in payload["perspectives"]} == {"implementation", "maintainer", "risk"}
    assert payload["preserved_dissent"]
    assert any("invoice" in item["claim"].lower() for item in payload["preserved_dissent"])
    assert payload["recommended_synthesis"]
    assert "blockers" in payload
    assert payload["next_ces_command"]
    assert "Notes render in export output." in payload["acceptance_criteria"]
    assert "Existing export rows stay intact." in payload["must_not_break"]
    assert "--acceptance 'Notes render in export output.'" in payload["next_ces_command"]
    assert "--must-not-break 'Existing export rows stay intact.'" in payload["next_ces_command"]
    assert any(
        "--acceptance 'Notes render in export output.'" in item["suggested_command"] for item in payload["alternatives"]
    )


def test_deliberate_global_json_flag_outputs_json(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["--json", "deliberate", "Add invoice notes", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["objective"] == "Add invoice notes"


def test_deliberate_markdown_surfaces_supplied_boundaries(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        [
            "deliberate",
            "Rotate production database credentials",
            "--project-root",
            str(tmp_path),
            "--acceptance",
            "New credentials pass smoke verification before cutover.",
            "--must-not-break",
            "Existing rollback path.",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "## Acceptance criteria" in result.stdout
    assert "New credentials pass smoke verification before cutover." in result.stdout
    assert "## Must not break" in result.stdout
    assert "Existing rollback path." in result.stdout
    assert "--acceptance 'New credentials pass smoke verification before cutover.'" in result.stdout
    assert "--must-not-break 'Existing rollback path.'" in result.stdout


def test_deliberate_high_risk_objective_preserves_blocking_pushback(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        [
            "deliberate",
            "Rotate production database credentials",
            "--project-root",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["decision"] == "needs_operator_decision"
    assert payload["blockers"]
    assert any("acceptance" in item.lower() or "credential" in item.lower() for item in payload["blockers"])
    assert any(item["blocking"] for item in payload["preserved_dissent"])
    assert payload["next_ces_command"] == "Clarify the request and rerun ces deliberate."


def test_deliberate_high_risk_with_boundaries_is_ready_and_preserves_flags(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        [
            "deliberate",
            "Rotate production database credentials",
            "--project-root",
            str(tmp_path),
            "--acceptance",
            "New credentials pass smoke verification before cutover.",
            "--must-not-break",
            "Existing rollback path.",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["decision"] == "ready_for_contract"
    assert "--acceptance 'New credentials pass smoke verification before cutover.'" in payload["next_ces_command"]
    assert "--must-not-break 'Existing rollback path.'" in payload["next_ces_command"]


def test_passport_json_contains_evidence_backed_summary(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["passport", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["detected_archetype"] == "python-package"
    assert payload["maturity_level"] == "shareable-app"
    assert payload["recommended_next_promotion"] == "production-candidate"
    assert payload["evidence_sources"]


def test_promote_json_is_read_only_sequential_plan(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(), ["promote", "production-candidate", "--project-root", str(tmp_path), "--format", "json"]
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    payload = json.loads(result.stdout)
    assert payload["target_level"] == "production-candidate"
    assert payload["execution_mode"] == "plan-only"
    assert payload["steps"][0]["target_maturity"] == "production-candidate"


def test_invariants_json_and_slop_scan_json(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)
    (tmp_path / "worker.py").write_text("try:\n    run()\nexcept Exception:\n    pass\n", encoding="utf-8")

    invariants = runner.invoke(_get_app(), ["invariants", "--project-root", str(tmp_path), "--format", "json"])
    slop = runner.invoke(_get_app(), ["slop-scan", "--project-root", str(tmp_path), "--format", "json"])

    assert invariants.exit_code == 0, invariants.stdout
    assert slop.exit_code == 0, slop.stdout
    assert json.loads(invariants.stdout)["invariants"]
    assert any(finding["category"] == "ai-slop" for finding in json.loads(slop.stdout)["findings"])


def test_launch_rehearsal_json_uses_nested_command_shape(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(_get_app(), ["launch", "rehearsal", "--project-root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "read-only-plan"
    assert "uv run pytest tests/ -q" in payload["recommended_commands"]


def test_ship_json_is_read_only_and_includes_objective(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(), ["ship", "Create a recipe app", "--project-root", str(tmp_path), "--format", "json"]
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (tmp_path / ".ces").exists()
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "read-only-plan"
    assert payload["objective"] == "Create a recipe app"
    assert payload["recommended_command"].startswith("ces build --from-scratch")


def test_ship_markdown_explains_safe_front_door(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["ship", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert "# CES Ship Plan" in result.stdout
    assert "read-only" in result.stdout
    assert "does not launch Codex or Claude Code" in result.stdout
    assert "ces build --from-scratch" in result.stdout


def test_create_interactive_collects_project_details_and_stays_read_only(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(),
        ["create", "--project-root", str(tmp_path)],
        input="Calm Notes\nCreate a tiny local notes app\n\n",
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (tmp_path / ".ces").exists()
    assert not (tmp_path / "calm-notes").exists()
    assert "Project name" in result.stdout
    assert "What do you want it to do?" in result.stdout
    assert "# CES Create Plan" in result.stdout
    assert "Execution mode: **interactive-read-only-wizard**" in result.stdout
    assert f"mkdir -p {tmp_path / 'calm-notes'} && cd {tmp_path / 'calm-notes'}" in result.stdout
    assert "ces build --from-scratch 'Create a tiny local notes app'" in result.stdout


def test_create_single_argument_treats_text_as_objective_and_infers_name(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        [
            "create",
            "Build a minimalist habit tracker",
            "--project-root",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["objective"] == "Build a minimalist habit tracker"
    assert payload["project_name"] == "Habit Tracker"
    assert payload["project_slug"] == "habit-tracker"
    assert payload["target_directory"] == str(tmp_path / "habit-tracker")
    assert not (tmp_path / "habit-tracker").exists()


def test_create_json_outputs_copy_paste_greenfield_sequence(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        [
            "create",
            "Calm Notes",
            "Create a tiny local notes app",
            "--project-root",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "interactive-read-only-wizard"
    assert payload["project_name"] == "Calm Notes"
    assert payload["project_slug"] == "calm-notes"
    assert payload["objective"] == "Create a tiny local notes app"
    assert payload["target_directory"] == str(tmp_path / "calm-notes")
    assert payload["commands"] == [
        f"mkdir -p {tmp_path / 'calm-notes'} && cd {tmp_path / 'calm-notes'}",
        "ces ship -- 'Create a tiny local notes app'",
        "ces build --from-scratch 'Create a tiny local notes app'",
        "ces verify",
        "ces proof",
    ]
    assert payload["safety_notes"][0].startswith("`ces create` is read-only")


def test_create_honors_root_json_with_single_objective_argument(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["--json", "create", "Create calm notes", "--project-root", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["project_name"] == "Calm Notes"
    assert payload["objective"] == "Create calm notes"


def test_create_json_requires_objective_when_no_argument(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["--json", "create", "--project-root", str(tmp_path)])

    assert result.exit_code != 0
    assert "objective is required" in result.stderr


def test_create_infers_clean_names_for_documented_examples(tmp_path: Path) -> None:
    examples = {
        "Create a small project-management app with tests and run instructions": "Project Management App",
        "Create a small task tracker app with add/list/complete tasks, tests, and a README": "Task Tracker App",
        "Build a minimalist habit tracker": "Habit Tracker",
    }

    for objective, expected_name in examples.items():
        result = runner.invoke(
            _get_app(),
            ["create", objective, "--project-root", str(tmp_path), "--format", "json"],
        )

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["project_name"] == expected_name


def test_create_supports_explicit_name_with_single_objective_argument(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        [
            "create",
            "Create a tiny local notes app",
            "--name",
            "Calm Notes",
            "--project-root",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["project_name"] == "Calm Notes"
    assert payload["objective"] == "Create a tiny local notes app"
    assert payload["project_slug"] == "calm-notes"


def test_create_quotes_shell_metacharacters_in_objective(tmp_path: Path) -> None:
    objective = "Create Bob's notes $(touch /tmp/pwned) and `whoami`"

    result = runner.invoke(
        _get_app(),
        ["create", "Shell Test", objective, "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["commands"][1].startswith("ces ship -- ")
    build_command = payload["commands"][2]
    assert build_command.startswith("ces build --from-scratch ")
    assert "$(touch /tmp/pwned)" in build_command
    assert "'\"'\"'" in build_command


def test_create_handles_option_like_objective_safely(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        ["create", "--project-root", str(tmp_path), "--format", "json", "Help App", "--", "--help"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["commands"][1] == "ces ship -- --help"
    assert payload["commands"][2] == "ces build --from-scratch=--help"


def test_create_quotes_project_root_with_spaces(tmp_path: Path) -> None:
    project_root = tmp_path / "space root"
    project_root.mkdir()

    result = runner.invoke(
        _get_app(),
        ["create", "Calm Notes", "Create notes", "--project-root", str(project_root), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert (
        payload["commands"][0]
        == f"mkdir -p {shlex.quote(str(project_root / 'calm-notes'))} && cd {shlex.quote(str(project_root / 'calm-notes'))}"
    )


def test_root_help_mentions_create_front_door() -> None:
    result = runner.invoke(_get_app(), ["--help"])

    assert result.exit_code == 0
    assert "ces create" in result.stdout
    assert "read-only new-project plan" in result.stdout.lower()
    assert "Legacy alias" not in result.stdout


def test_legacy_run_alias_still_has_help_while_hidden_from_root_help() -> None:
    result = runner.invoke(_get_app(), ["run", "--help"])

    assert result.exit_code == 0
    cleaned = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", result.stdout)
    assert "Usage: ces run" in cleaned
    assert "Legacy alias for the guided local-first build flow." in cleaned


def test_create_help_makes_read_only_project_root_boundary_explicit() -> None:
    result = runner.invoke(_get_app(), ["create", "--help"])

    assert result.exit_code == 0
    assert "read-only new-project creation plan" in result.stdout.lower()
    assert "no files are created" in result.stdout.lower()
    assert "should be created" not in result.stdout.lower()


def test_root_no_args_shows_start_here_help_instead_of_missing_command_error() -> None:
    result = runner.invoke(_get_app(), [])

    assert result.exit_code == 0
    assert "Start Here" in result.stdout
    assert "ces create" in result.stdout
    assert "ces start" in result.stdout
    assert "Missing command" not in result.stderr


def test_start_interactive_prompts_for_objective_and_stays_read_only(tmp_path: Path) -> None:
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(), ["start", "--project-root", str(tmp_path)], input="Create a calm habit tracker\n"
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    assert not (tmp_path / ".ces").exists()
    assert "What do you want to build?" in result.stdout
    assert "# CES Guided Start" in result.stdout
    assert "Objective: Create a calm habit tracker" in result.stdout
    assert "Step 1: Plan" in result.stdout
    assert "Step 2: Build" in result.stdout
    assert "Step 3: Verify" in result.stdout
    assert "Step 4: Prove" in result.stdout
    assert "ces build --from-scratch 'Create a calm habit tracker'" in result.stdout


def test_start_json_outputs_beginner_guided_stages(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        ["start", "Create a note app", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "interactive-read-only-guide"
    assert payload["objective"] == "Create a note app"
    assert [stage["name"] for stage in payload["stages"]] == ["Plan", "Build", "Verify", "Prove"]
    assert payload["stages"][1]["command"] == "ces build --from-scratch 'Create a note app'"
    assert payload["safety_notes"][0].startswith("`ces start` is read-only")


def test_start_honors_root_json_flag(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        ["--json", "start", "Create a note app", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "interactive-read-only-guide"
    assert payload["objective"] == "Create a note app"


def test_start_requires_objective_for_noninteractive_json(tmp_path: Path) -> None:
    result = runner.invoke(_get_app(), ["--json", "start", "--project-root", str(tmp_path)])

    assert result.exit_code != 0
    assert "objective is required" in result.stderr


def test_start_existing_repo_uses_brownfield_path_instead_of_greenfield(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(),
        ["start", "Improve this app", "--project-root", str(tmp_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [stage["name"] for stage in payload["stages"]] == ["Plan", "Inspect", "Build", "Verify", "Prove"]
    assert payload["stages"][1]["command"] == "ces mri && ces next"
    assert payload["stages"][2]["command"].startswith("ces build ")
    assert "--from-scratch" not in payload["stages"][2]["command"]
    assert "--gsd" not in payload["stages"][2]["command"]


def test_ship_existing_repo_recommends_brownfield_sequence(tmp_path: Path) -> None:
    _write_minimal_project(tmp_path)

    result = runner.invoke(
        _get_app(), ["ship", "Improve this app", "--project-root", str(tmp_path), "--format", "json"]
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["recommended_command"].startswith("ces build ")
    assert "--from-scratch" not in payload["recommended_command"]
    assert payload["recommended_commands"][:4] == ["ces doctor", "ces mri", "ces next", "ces next-prompt"]
    assert "ces verify" in payload["recommended_commands"]
    assert "ces proof" in payload["recommended_commands"]


def test_start_guided_payload_uses_double_dash_for_dash_prefixed_objective(tmp_path: Path) -> None:
    result = runner.invoke(
        _get_app(),
        ["start", "--project-root", str(tmp_path), "--format", "json", "--", "-make a timer"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["stages"][0]["command"] == "ces ship -- '-make a timer'"


def test_create_existing_target_directory_warns_before_from_scratch(tmp_path: Path) -> None:
    existing = tmp_path / "calm-notes"
    existing.mkdir()
    (existing / "pyproject.toml").write_text("[project]\nname='calm-notes'\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    result = runner.invoke(
        _get_app(),
        ["create", "Calm Notes", "Create notes", "--project-root", str(tmp_path), "--format", "json"],
    )

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert result.exit_code == 0, result.stdout
    assert before == after
    payload = json.loads(result.stdout)
    assert payload["target_exists"] is True
    assert any("Target directory already exists" in note for note in payload["safety_notes"])
