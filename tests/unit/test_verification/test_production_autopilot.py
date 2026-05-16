"""Tests for deterministic Production Autopilot report modeling."""

from __future__ import annotations

import json
from pathlib import Path


def test_mri_report_includes_readiness_score_and_ladder(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "pyproject.toml").write_text(
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
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    payload = scan_project_mri(tmp_path).to_dict()

    assert payload["readiness_score"] == {
        "score": 55,
        "max_score": 100,
        "passed": ["documentation", "project", "quality", "tests"],
        "missing": ["ces", "ci", "runtime"],
    }
    assert payload["maturity_ladder"] == [
        "vibe-prototype",
        "local-app",
        "shareable-app",
        "production-candidate",
        "production-ready",
    ]


def test_project_archetype_detection_is_more_specific(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "api"
dependencies = ["fastapi", "uvicorn"]
""".strip(),
        encoding="utf-8",
    )

    assert scan_project_mri(tmp_path).project_type == "fastapi-app"


def test_slop_findings_detect_weak_tests_and_broad_exception_swallowing(tmp_path: Path) -> None:
    from ces.verification.mri import scan_project_mri

    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    exception_name = "Exception"
    (tmp_path / "script.py").write_text(
        f"def run():\n    try:\n        risky()\n    except {exception_name}:\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_weak.py").write_text("def test_weak():\n    pass\n", encoding="utf-8")

    report = scan_project_mri(tmp_path)
    titles = {finding.title for finding in report.risk_findings}

    assert "Assertion-free or trivial tests detected" in titles
    assert "Broad exception swallowing detected" in titles


def test_production_passport_json_is_deterministic_and_read_only(tmp_path: Path) -> None:
    from ces.verification.mri import build_production_passport

    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    first = build_production_passport(tmp_path).to_json()
    second = build_production_passport(tmp_path).to_json()
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    payload = json.loads(first)

    assert first == second
    assert before == after
    assert payload["project_root"] == str(tmp_path.resolve())
    assert payload["detected_archetype"] == "node-app"
    assert "readiness_score" in payload
    assert "evidence_sources" in payload


def test_next_action_and_prompt_are_guardrailed(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_action, build_next_prompt

    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    next_action = build_next_action(tmp_path)
    prompt = build_next_prompt(tmp_path)

    assert next_action.current_maturity == "vibe-prototype"
    assert next_action.target_maturity == "local-app"
    assert next_action.recommended_command.startswith("ces build")
    rendered = prompt.to_markdown()
    assert "# CES Developer Intent Contract" in rendered
    assert "Project mode" in rendered
    assert "Verification commands" in rendered
    assert "Non-goals" in rendered
    assert "Exact `ces:completion` expectations" in rendered


def test_empty_project_next_action_recommends_greenfield_from_scratch(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_action, build_next_prompt

    action = build_next_action(tmp_path)
    prompt = build_next_prompt(tmp_path, "Create a tiny tracker")

    assert action.current_maturity == "vibe-prototype"
    assert action.recommended_command.startswith("ces build --from-scratch")
    assert "Create a small runnable app" in action.recommended_command
    assert "README" in action.recommended_command
    assert "tests" in action.recommended_command
    payload = prompt.to_dict()
    assert payload["project_mode"] == "greenfield"
    assert payload["original_objective"] == "Create a tiny tracker"
    assert "README documents how to run, test, and verify the project locally." in payload["acceptance_criteria"]


def test_production_passport_marks_incomplete_readiness_without_fake_none(tmp_path: Path) -> None:
    from ces.verification.mri import build_production_passport

    rendered = build_production_passport(tmp_path).to_markdown()
    blockers_section = rendered.split("## Blockers", 1)[1].split("## Missing", 1)[0]

    assert "No critical/high blockers detected" in blockers_section
    assert "Readiness is incomplete" in blockers_section
    assert "- None detected." not in blockers_section


def test_ship_plan_is_read_only_beginner_front_door(tmp_path: Path) -> None:
    from ces.verification.mri import build_ship_plan

    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    plan = build_ship_plan(tmp_path, objective="Create a habit tracker app")

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    payload = plan.to_dict()
    assert before == after
    assert payload["execution_mode"] == "read-only-plan"
    assert payload["objective"] == "Create a habit tracker app"
    assert payload["recommended_command"].startswith("ces build --from-scratch")
    assert "ces doctor" in payload["recommended_commands"]
    assert any(command.startswith("ces build --from-scratch") for command in payload["recommended_commands"])
    assert "does not launch Codex or Claude Code" in plan.to_markdown()


def test_ship_plan_shell_quotes_greenfield_objective(tmp_path: Path) -> None:
    from ces.verification.mri import build_ship_plan

    plan = build_ship_plan(tmp_path, objective="Create app $(touch /tmp/ces-ship-pwned) with `whoami`")
    command = plan.to_dict()["recommended_command"]

    assert command == "ces build --from-scratch 'Create app $(touch /tmp/ces-ship-pwned) with `whoami`'"
    assert command in plan.to_markdown()


def test_ship_plan_uses_option_safe_greenfield_objective(tmp_path: Path) -> None:
    from ces.verification.mri import build_ship_plan

    plan = build_ship_plan(tmp_path, objective="--help")
    payload = plan.to_dict()

    assert payload["recommended_command"] == "ces build --from-scratch=--help"
    assert "ces build --from-scratch=--help" in payload["recommended_commands"]


def test_ship_plan_routes_existing_repo_to_readiness_gap_work(tmp_path: Path) -> None:
    from ces.verification.mri import build_ship_plan

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\nversion = '0.1.0'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    plan = build_ship_plan(tmp_path, objective="Add billing")

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    payload = plan.to_dict()
    assert before == after
    assert (
        payload["recommended_command"]
        == 'ces build "Add the next missing production-readiness signal reported by ces next"'
    )
    assert "ces mri" in payload["recommended_commands"]
    assert "ces next-prompt" in payload["recommended_commands"]
    assert not any(command.startswith("ces build --from-scratch") for command in payload["recommended_commands"])


def test_next_prompt_json_shape_is_stable_and_read_only(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_prompt

    (tmp_path / "README.md").write_text("# Demo\nRun: `python app.py`\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
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
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "verification-profile.json").write_text("{}\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))

    payload = build_next_prompt(
        tmp_path,
        "Add invoice notes to exports",
        acceptance_criteria=("Export includes note text.",),
        must_not_break=("Existing CSV columns remain stable.",),
    ).to_dict()

    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
    assert before == after
    assert list(payload) == [
        "schema_version",
        "next_action",
        "project_root",
        "original_objective",
        "contract_status",
        "project_mode",
        "project_mode_reason",
        "detected_project_type",
        "detected_maturity",
        "intent_gate",
        "scope",
        "acceptance_criteria",
        "must_not_break",
        "allowed_file_areas",
        "forbidden_changes",
        "slop_budget",
        "scope_drift_kill_switch",
        "slop_risks",
        "thin_rescue_signals",
        "prompt",
        "validation_commands",
        "non_goals",
        "completion_evidence_required",
        "ces_completion_expectations",
        "next_ces_command_after_implementation",
    ]
    assert payload["contract_status"] == "implementation-ready"
    assert payload["project_mode"] == "brownfield"
    assert payload["acceptance_criteria"] == ["Export includes note text."]
    assert "Existing CSV columns remain stable." in payload["must_not_break"]
    assert payload["next_ces_command_after_implementation"] == "ces verify"


def test_next_prompt_brownfield_allowed_file_areas_include_objective_matched_source_paths(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_prompt

    (tmp_path / "README.md").write_text("# Demo\nRun: `uv run demo --help`\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
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
    (tmp_path / "src" / "billing").mkdir(parents=True)
    (tmp_path / "src" / "billing" / "exports.py").write_text("def export_rows():\n    return []\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_exports.py").write_text("def test_exports():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (tmp_path / ".ces").mkdir()
    (tmp_path / ".ces" / "verification-profile.json").write_text("{}\n", encoding="utf-8")

    payload = build_next_prompt(tmp_path, "Add invoice notes to CSV exports").to_dict()

    assert payload["project_mode"] == "brownfield"
    assert "src/billing/exports.py" in payload["allowed_file_areas"]
    assert "tests/" in payload["allowed_file_areas"]


def test_next_prompt_detects_thin_born_thin_rescue_mode(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_prompt

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'thin-app'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")

    payload = build_next_prompt(tmp_path, "Add a dashboard").to_dict()

    assert payload["project_mode"] == "thin/born-thin rescue"
    thin = payload["thin_rescue_signals"]
    assert thin is not None
    assert thin["missing_readme"] is True
    assert thin["missing_run_instructions"] is True
    assert thin["missing_tests"] is True
    assert thin["weak_project_spine"] is True
    assert "Single safest next step" in payload["prompt"]


def test_next_prompt_reflects_slop_scan_findings(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_prompt

    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    exception_name = "Exception"
    (tmp_path / "worker.py").write_text(
        f"def run():\n    try:\n        risky()\n    except {exception_name}:\n        pass\n",
        encoding="utf-8",
    )

    payload = build_next_prompt(tmp_path, "Rescue this repo").to_dict()

    assert payload["slop_risks"]
    assert payload["slop_risks"][0]["title"] == "Broad exception swallowing detected"
    assert "AI-Slop Risks" in payload["prompt"]


def test_next_prompt_blocks_high_risk_vague_objective_without_acceptance(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_prompt

    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    payload = build_next_prompt(tmp_path, "Rotate production database credentials").to_dict()

    assert payload["contract_status"] == "blocked"
    assert payload["intent_gate"]["decision"] == "blocked"
    assert payload["next_ces_command_after_implementation"] == "Clarify the request and rerun ces next-prompt."
    assert "Do not start implementation yet." in payload["scope"]


def test_invariant_mining_is_conservative_and_evidence_backed(tmp_path: Path) -> None:
    from ces.verification.mri import mine_project_invariants

    (tmp_path / "README.md").write_text(
        """
# Demo

Safety invariant: Never print secret values.
Public boundary: local-first CLI only.
""".strip(),
        encoding="utf-8",
    )

    report = mine_project_invariants(tmp_path)

    assert [item.text for item in report.invariants] == [
        "Public boundary: local-first CLI only.",
        "Safety invariant: Never print secret values.",
    ]
    assert {item.source for item in report.invariants} == {"README.md:3", "README.md:4"}


def test_launch_rehearsal_recommends_non_destructive_commands(tmp_path: Path) -> None:
    from ces.verification.mri import build_launch_rehearsal

    (tmp_path / "pyproject.toml").write_text(
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

    report = build_launch_rehearsal(tmp_path)

    assert report.mode == "read-only-plan"
    assert "uv run pytest tests/ -q" in report.recommended_commands
    assert "uv run ruff check ." in report.recommended_commands
    assert all(command.category in {"recommended", "smoke"} for command in report.commands)


def test_launch_rehearsal_uses_bun_commands_for_bun_projects(tmp_path: Path) -> None:
    from ces.verification.mri import build_launch_rehearsal

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "bun test", "build": "bun build ./src/index.ts"}}),
        encoding="utf-8",
    )
    (tmp_path / "bun.lock").write_text("", encoding="utf-8")

    report = build_launch_rehearsal(tmp_path)

    assert "bun run test" in report.recommended_commands
    assert "npm test" not in report.recommended_commands
