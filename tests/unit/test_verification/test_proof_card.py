"""Tests for beginner-facing proof cards."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _write_completion_contract(root: Path) -> None:
    ces_dir = root / ".ces"
    ces_dir.mkdir()
    (ces_dir / "completion-contract.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": "Create a tiny CLI calculator",
                "project_type": "python-cli",
                "acceptance_criteria": [],
                "inferred_commands": [
                    {
                        "id": "cli-smoke",
                        "kind": "smoke",
                        "command": "python app.py --help",
                        "reason": "CLI smoke",
                        "expected_exit_codes": [0],
                    },
                    {
                        "id": "tests",
                        "kind": "test",
                        "command": "pytest",
                        "reason": "test suite",
                        "expected_exit_codes": [0],
                    },
                ],
                "runtime": {"name": "codex"},
                "required_artifacts": ["README.md", "run command", "test command", "verification evidence"],
                "proof_requirements": [
                    "README includes beginner run and test instructions",
                    "At least one runnable smoke command is verified",
                ],
                "next_ces_command": "ces verify --json",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_latest_verification(root: Path, *, passed: bool = True) -> None:
    (root / ".ces" / "latest-verification.json").write_text(
        json.dumps(
            {
                "verification": {
                    "passed": passed,
                    "commands": [
                        {
                            "id": "cli-smoke",
                            "kind": "smoke",
                            "command": "python app.py --help",
                            "required": True,
                            "exit_code": 0 if passed else 1,
                            "stdout": "",
                            "stderr": "",
                            "expected_exit_codes": [0],
                            "passed": passed,
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_proof_card_json_summarizes_claims_and_no_ship_gaps(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")

    card = build_proof_card(tmp_path)
    payload = card.to_dict()

    assert payload["objective"] == "Create a tiny CLI calculator"
    assert payload["ship_recommendation"] == "no-ship"
    assert payload["evidence_status"] == "incomplete"
    assert "README.md" in payload["missing_required_artifacts"]
    assert "verification evidence" in payload["missing_required_artifacts"]
    assert payload["commands_run"] == []
    assert payload["verification_commands"][0]["command"] == "python app.py --help"
    assert payload["next_command"] == "ces verify --json"


def test_proof_card_marks_candidate_when_required_beginner_artifacts_exist(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Calculator\n\nRun: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    card = build_proof_card(tmp_path)
    payload = card.to_dict()

    assert payload["evidence_status"] == "candidate"
    assert payload["ship_recommendation"] == "candidate"
    assert payload["missing_required_artifacts"] == []
    markdown = card.to_markdown()
    assert "# CES Proof Card" in markdown
    assert "Ship recommendation: **candidate**" in markdown
    assert "python app.py --help" in markdown


def test_proof_card_without_contract_is_honest_no_ship(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    card = build_proof_card(tmp_path)
    payload = card.to_dict()

    assert payload["objective"] is None
    assert payload["ship_recommendation"] == "no-ship"
    assert any("completion contract" in item for item in payload["unproven_areas"])


def test_proof_card_does_not_overclaim_from_readme_without_persisted_verification(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: smoke passed.\n",
        encoding="utf-8",
    )

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["ship_recommendation"] == "no-ship"
    assert "verification evidence" in payload["missing_required_artifacts"]
    assert any("No persisted verification run" in item for item in payload["unproven_areas"])


def test_proof_card_does_not_overclaim_failed_persisted_verification(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path, passed=False)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: smoke failed.\n",
        encoding="utf-8",
    )

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["ship_recommendation"] == "no-ship"
    assert payload["commands_run"][0]["passed"] is False
    assert any("did not pass" in item for item in payload["unproven_areas"])


def test_changed_files_uses_read_only_nul_porcelain(monkeypatch, tmp_path: Path) -> None:
    from ces.verification import proof_card

    calls: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=b" M src/app.py\0?? docs/file with spaces.md\0R  new name.py\0old name.py\0",
            stderr=b"",
        )

    monkeypatch.setattr(proof_card.shutil, "which", lambda name: "/usr/bin/git" if name == "git" else None)
    monkeypatch.setattr(proof_card.subprocess, "run", fake_run)

    assert proof_card._changed_files(tmp_path) == ("src/app.py", "docs/file with spaces.md", "new name.py")
    assert calls
    args = calls[0]["args"]
    assert isinstance(args, list)
    assert "--no-optional-locks" in args
    assert "--porcelain=v1" in args
    assert "-z" in args
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
