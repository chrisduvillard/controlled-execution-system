"""Tests for the ces harness command group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _get_app() -> Any:
    from ces.cli import app

    return app


def _manifest_file(tmp_path: Path, *, valid: bool = True) -> Path:
    payload: dict[str, object] = {
        "change_id": "hchg-cli-validate",
        "title": "Change validation guidance",
        "component_type": "tool_policy",
        "files_changed": ["src/ces/harness/policy.md"],
        "evidence_refs": ["analysis:proxy-validation"],
        "failure_pattern": "Proxy validation was accepted.",
        "root_cause_hypothesis": "Policy was under-specified.",
        "predicted_fixes": ["Reject proxy-only checks."],
        "predicted_regressions": ["More blocked completions."],
        "validation_plan": ["Run focused dogfood transcript."],
        "rollback_condition": "Rollback if false blocks increase.",
    }
    if not valid:
        payload["change_id"] = "bad"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _analysis_file(tmp_path: Path) -> Path:
    payload: dict[str, object] = {
        "task_run_id": "run-memory",
        "outcome": "fail",
        "failure_class": "proxy_validation",
        "suspected_root_cause": "Runtime accepted compile-only checks as success evidence.",
        "validation_commands_observed": ["python -m py_compile src/app.py"],
        "proxy_validation_warnings": ["compile-only validation was used"],
        "evidence_pointers": ["analysis.json#proxy-validation"],
    }
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_harness_init_dry_run_shows_layout_without_writing(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "init", "--dry-run"])

    assert result.exit_code == 0, result.stdout
    assert ".ces/harness/index.json" in result.stdout
    assert ".ces/harness/change_manifests/" in result.stdout
    assert not (tmp_path / ".ces").exists()


def test_harness_init_creates_expected_local_layout(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "init"])

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".ces" / "harness" / "index.json").is_file()
    assert (tmp_path / ".ces" / "harness" / "change_manifests").is_dir()
    assert not (tmp_path / ".ces" / "state.db").exists()
    assert not (tmp_path / ".ces" / "keys").exists()


def test_harness_inspect_without_init_points_to_next_action(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "inspect"])

    assert result.exit_code == 1
    assert "ces harness init" in result.stdout


def test_harness_changes_validate_accepts_valid_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_path = _manifest_file(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "changes", "validate", str(manifest_path)])

    assert result.exit_code == 0, result.stdout
    assert "valid" in result.stdout.lower()
    assert "predicted fixes" in result.stdout.lower()
    assert "predicted regressions" in result.stdout.lower()


def test_harness_changes_validate_rejects_invalid_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_path = _manifest_file(tmp_path, valid=False)

    result = runner.invoke(_get_app(), ["harness", "changes", "validate", str(manifest_path)])

    assert result.exit_code != 0
    assert "invalid" in result.stdout.lower()


def test_harness_changes_validate_rejects_secret_in_unknown_field_without_echoing_it(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_path = _manifest_file(tmp_path)
    secret_value = "OPENAI_API_KEY=***"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["api_key"] = secret_value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    result = runner.invoke(_get_app(), ["harness", "changes", "validate", str(manifest_path)])

    assert result.exit_code != 0
    assert "invalid" in result.stdout.lower()
    assert secret_value not in result.stdout
    assert "***" not in result.stdout


def test_harness_changes_add_persists_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_path = _manifest_file(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "changes", "add", str(manifest_path)])

    assert result.exit_code == 0, result.stdout
    assert "saved harness change: hchg-cli-validate" in result.stdout
    assert (tmp_path / ".ces" / "state.db").is_file()


def test_harness_changes_list_and_show_read_persisted_manifests(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    manifest_path = _manifest_file(tmp_path)
    add_result = runner.invoke(_get_app(), ["harness", "changes", "add", str(manifest_path)])
    assert add_result.exit_code == 0, add_result.stdout

    list_result = runner.invoke(_get_app(), ["harness", "changes", "list"])
    show_result = runner.invoke(_get_app(), ["harness", "changes", "show", "hchg-cli-validate"])

    assert list_result.exit_code == 0, list_result.stdout
    assert "hchg-cli-validate" in list_result.stdout
    assert "tool_policy" in list_result.stdout
    assert show_result.exit_code == 0, show_result.stdout
    assert "Reject proxy validation" not in show_result.stdout
    assert "Change validation guidance" in show_result.stdout
    assert "manifest hash" in show_result.stdout.lower()


def test_harness_changes_show_missing_change_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(_get_app(), ["harness", "changes", "show", "hchg-missing"])

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_harness_memory_draft_activate_and_list(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    analysis_path = _analysis_file(tmp_path)

    draft_result = runner.invoke(_get_app(), ["harness", "memory", "draft", "--from-analysis", str(analysis_path)])

    assert draft_result.exit_code == 0, draft_result.stdout
    assert "saved harness memory lesson" in draft_result.stdout
    assert "status: draft" in draft_result.stdout
    lesson_id = next(
        line.split(": ", 1)[1] for line in draft_result.stdout.splitlines() if line.startswith("lesson id:")
    )

    list_draft_result = runner.invoke(_get_app(), ["harness", "memory", "list"])
    assert list_draft_result.exit_code == 0, list_draft_result.stdout
    assert lesson_id in list_draft_result.stdout
    assert "draft" in list_draft_result.stdout

    activate_result = runner.invoke(_get_app(), ["harness", "memory", "activate", lesson_id])
    assert activate_result.exit_code == 0, activate_result.stdout
    assert "status: active" in activate_result.stdout

    archive_result = runner.invoke(_get_app(), ["harness", "memory", "archive", lesson_id])
    assert archive_result.exit_code == 0, archive_result.stdout
    assert "status: archived" in archive_result.stdout

    reactivate_result = runner.invoke(_get_app(), ["harness", "memory", "activate", lesson_id])
    assert reactivate_result.exit_code == 0, reactivate_result.stdout
    assert "status: active" in reactivate_result.stdout

    list_active_result = runner.invoke(_get_app(), ["harness", "memory", "list", "--status", "active"])
    assert list_active_result.exit_code == 0, list_active_result.stdout
    assert lesson_id in list_active_result.stdout
    assert "hash=" in list_active_result.stdout.lower()
