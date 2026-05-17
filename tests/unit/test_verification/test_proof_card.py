"""Tests for beginner-facing proof cards."""

from __future__ import annotations

import json
import os
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
                            "cwd": ".",
                            "timeout_seconds": 120,
                            "expected_exit_codes": [0],
                            "passed": passed,
                        },
                        {
                            "id": "tests",
                            "kind": "test",
                            "command": "pytest",
                            "required": True,
                            "exit_code": 0 if passed else 1,
                            "stdout": "",
                            "stderr": "",
                            "cwd": ".",
                            "timeout_seconds": 120,
                            "expected_exit_codes": [0],
                            "passed": passed,
                        },
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

    assert payload["proof_status"] == "proven"
    assert payload["approval_safety"] == "safe-to-review"
    assert payload["evidence_status"] == "candidate"
    assert payload["ship_recommendation"] == "candidate"
    assert payload["review_summary"] == {
        "decision": "ready-for-review",
        "approval_gate": "open",
        "primary_blocker": None,
        "freshness": "fresh",
        "command_coverage": "2/2 required commands verified",
        "artifact_coverage": "4/4 required artifacts present",
        "behavior_delta_coverage": "0 recorded / 0 unresolved ambiguity",
        "risk_track": "C",
        "risk_evidence": "low-risk: no additional risk evidence required",
        "next_steps": ["Review changed files and evidence, then run `ces approve` if satisfied."],
    }
    assert payload["missing_required_artifacts"] == []
    markdown = card.to_markdown()
    assert "# CES Proof Card" in markdown
    assert "## Review decision" in markdown
    assert "Decision: **ready-for-review**" in markdown
    assert "Approval gate: **open**" in markdown
    assert "Command coverage: 2/2 required commands verified" in markdown
    assert "Behavior delta coverage: 0 recorded / 0 unresolved ambiguity" in markdown
    assert "Risk track: C" in markdown
    assert "Risk evidence: low-risk: no additional risk evidence required" in markdown
    assert "Proof status: **proven**" in markdown
    assert "Ship recommendation: **candidate**" in markdown
    assert "python app.py --help" in markdown


def test_proof_card_surfaces_behavior_delta_and_blocks_unknowns(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    contract_path = tmp_path / ".ces" / "completion-contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["behavior_delta"] = {
        "added": ["CSV export includes invoice notes."],
        "modified": ["CSV export writes an extra notes column."],
        "removed": [],
        "preserved": ["Existing CSV column order remains stable."],
        "unknown": ["Downstream importers are not yet checked."],
    }
    payload["risk_track"] = {
        "tier": "A",
        "required_artifacts": ["rollback-plan.md", "reviewer-signoff.md"],
        "proof_requirements": ["Document high-risk behavior evidence."],
        "evidence_requirements": ["Fresh verification passed.", "Rollback path documented."],
    }
    contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Calculator\n\nRun: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )

    result = build_proof_card(tmp_path).to_dict()

    assert result["proof_status"] == "partially_proven"
    assert result["approval_safety"] == "needs-evidence"
    assert result["behavior_delta"] == payload["behavior_delta"]
    assert result["review_summary"]["behavior_delta_coverage"] == "4 recorded / 1 unresolved ambiguity"
    assert result["review_summary"]["risk_track"] == "A"
    assert result["review_summary"]["risk_evidence"] == "0/2 risk artifacts present"
    assert "rollback-plan.md" in result["missing_required_artifacts"]
    assert "reviewer-signoff.md" in result["missing_required_artifacts"]
    assert result["review_summary"]["primary_blocker"] == "Required beginner handoff artifacts are incomplete."
    assert any(
        item == "Unresolved behavior ambiguity remains: Downstream importers are not yet checked."
        for item in result["unproven_areas"]
    )
    assert any("Unresolved behavior ambiguity" in item for item in result["unproven_areas"])
    assert result["review_summary"]["next_steps"][0] == (
        "Resolve unresolved behavior ambiguity or attach explicit evidence for it, then rerun `ces verify --json`."
    )
    markdown = build_proof_card(tmp_path).to_markdown()
    assert "## Behavior delta" in markdown
    assert "Added:" in markdown
    assert "Unresolved ambiguity:" in markdown
    assert "Unknown:" not in markdown


def test_proof_card_marks_partial_when_verification_passes_but_artifacts_are_missing(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text("Run: `python app.py --help`\n", encoding="utf-8")

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["proof_status"] == "partially_proven"
    assert payload["approval_safety"] == "needs-evidence"
    assert payload["ship_recommendation"] == "no-ship"
    assert payload["review_summary"]["decision"] == "needs-evidence"
    assert payload["review_summary"]["approval_gate"] == "closed"
    assert payload["review_summary"]["primary_blocker"] == "Required beginner handoff artifacts are incomplete."
    assert (
        "Repair missing evidence/artifacts, then rerun `ces verify --json`." in payload["review_summary"]["next_steps"]
    )


def test_proof_card_marks_contradicted_when_latest_verification_failed(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path, passed=False)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: smoke failed.\n",
        encoding="utf-8",
    )

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["proof_status"] == "contradicted"
    assert payload["approval_safety"] == "blocked"
    assert payload["ship_recommendation"] == "no-ship"
    assert payload["review_summary"]["decision"] == "blocked"
    assert payload["review_summary"]["primary_blocker"] == "Latest persisted verification run did not pass."


def test_proof_card_rejects_stale_verification_older_than_completion_contract(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )
    verification_path = tmp_path / ".ces" / "latest-verification.json"
    contract_path = tmp_path / ".ces" / "completion-contract.json"
    os.utime(verification_path, (1000, 1000))
    os.utime(contract_path, (2000, 2000))

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["proof_status"] == "unproven"
    assert payload["approval_safety"] == "needs-fresh-verification"
    assert payload["ship_recommendation"] == "no-ship"
    assert any("not fresh" in item for item in payload["unproven_areas"])


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


def test_proof_card_rejects_latest_verification_not_matching_current_contract(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    (tmp_path / ".ces" / "latest-verification.json").write_text(
        json.dumps(
            {
                "verification": {
                    "passed": True,
                    "commands": [
                        {
                            "id": "old-smoke",
                            "kind": "smoke",
                            "command": "true",
                            "required": True,
                            "exit_code": 0,
                            "stdout": "",
                            "stderr": "",
                            "cwd": ".",
                            "timeout_seconds": 120,
                            "expected_exit_codes": [0],
                            "passed": True,
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: old smoke passed.\n",
        encoding="utf-8",
    )

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["ship_recommendation"] == "no-ship"
    assert any("does not match the current completion contract" in item for item in payload["unproven_areas"])


def test_proof_card_rejects_required_artifact_paths_outside_project(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    contract_path = tmp_path / ".ces" / "completion-contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["required_artifacts"] = [
        "README.md",
        "run command",
        "test command",
        "verification evidence",
        "/etc/passwd",
        "../outside-proof.txt",
    ]
    contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (tmp_path.parent / "outside-proof.txt").write_text("outside\n", encoding="utf-8")
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )

    result = build_proof_card(tmp_path).to_dict()

    assert result["ship_recommendation"] == "no-ship"
    assert "/etc/passwd" in result["missing_required_artifacts"]
    assert "../outside-proof.txt" in result["missing_required_artifacts"]


def test_proof_card_shareable_output_omits_raw_stdout_stderr_and_absolute_root(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    latest_path = tmp_path / ".ces" / "latest-verification.json"
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    payload["verification"]["commands"][0]["stdout"] = "OPENAI_API_KEY=sk-supersecretvalue"
    payload["verification"]["commands"][0]["stderr"] = f"local path {tmp_path}"
    latest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "Run: `python app.py --help`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )

    output = build_proof_card(tmp_path).to_json()

    assert "sk-supersecretvalue" not in output
    assert "OPENAI_API_KEY" not in output
    assert str(tmp_path) not in output
    assert "stdout" not in output
    assert "stderr" not in output


def test_proof_card_requires_real_readme_run_and_test_instructions_not_incidental_words(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    _write_latest_verification(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Calculator\n\nRuntime tests are planned before launch. Verification evidence exists elsewhere.\n",
        encoding="utf-8",
    )

    payload = build_proof_card(tmp_path).to_dict()

    assert payload["ship_recommendation"] == "no-ship"
    assert "run command" in payload["missing_required_artifacts"]
    assert "test command" in payload["missing_required_artifacts"]


def test_proof_card_rejects_verification_with_mismatched_expected_exit_codes(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    contract_path = tmp_path / ".ces" / "completion-contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["inferred_commands"][0]["command"] = "false"
    payload["inferred_commands"][0]["expected_exit_codes"] = [0]
    payload["inferred_commands"] = payload["inferred_commands"][:1]
    contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (tmp_path / ".ces" / "latest-verification.json").write_text(
        json.dumps(
            {
                "verification": {
                    "passed": True,
                    "commands": [
                        {
                            "id": "cli-smoke",
                            "kind": "smoke",
                            "command": "false",
                            "required": True,
                            "exit_code": 1,
                            "stdout": "",
                            "stderr": "",
                            "cwd": ".",
                            "timeout_seconds": 120,
                            "expected_exit_codes": [1],
                            "passed": True,
                        }
                    ],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Run: `false`\n\nTest: `pytest`\n\nVerification evidence: local smoke passed.\n",
        encoding="utf-8",
    )

    result = build_proof_card(tmp_path).to_dict()

    assert result["ship_recommendation"] == "no-ship"
    assert any("does not match the current completion contract" in item for item in result["unproven_areas"])


def test_proof_card_scrubs_inline_secret_from_verification_commands(tmp_path: Path) -> None:
    from ces.verification.proof_card import build_proof_card

    _write_completion_contract(tmp_path)
    contract_path = tmp_path / ".ces" / "completion-contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["inferred_commands"][0]["command"] = "OPENAI_API_KEY=sk-sup...alue python app.py"
    contract_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    output = build_proof_card(tmp_path).to_json()

    assert "sk-sup...alue" not in output
    assert "OPENAI_API_KEY" in output
