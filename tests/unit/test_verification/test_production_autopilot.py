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
