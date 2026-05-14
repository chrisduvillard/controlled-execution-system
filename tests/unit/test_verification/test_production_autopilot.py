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
    (tmp_path / "script.py").write_text(
        """
def run():
    try:
        risky()
    except Exception:
        pass
""".strip(),
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
    assert "Secret-handling rule" in rendered
    assert "Validation commands" in rendered
    assert "Non-goals" in rendered
    assert "Completion evidence" in rendered


def test_empty_project_next_action_recommends_greenfield_from_scratch(tmp_path: Path) -> None:
    from ces.verification.mri import build_next_action, build_next_prompt

    action = build_next_action(tmp_path)
    prompt = build_next_prompt(tmp_path)

    assert action.current_maturity == "vibe-prototype"
    assert action.recommended_command.startswith("ces build --from-scratch")
    assert "Create a small runnable app" in action.recommended_command
    assert "README" in action.recommended_command
    assert "tests" in action.recommended_command
    assert "--from-scratch" in prompt.to_markdown()


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
