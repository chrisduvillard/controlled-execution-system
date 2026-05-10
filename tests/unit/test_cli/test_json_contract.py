"""CLI JSON contract matrix tests.

These tests cover representative read-only commands that API consumers are
likely to automate. They intentionally assert the public stream contract rather
than exact payload snapshots.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ces.cli import app
from ces.cli._output import set_json_mode

RICH_OR_ANSI_MARKERS = ("╭", "╮", "╰", "╯", "│", "\x1b[")


@pytest.fixture(autouse=True)
def _reset_json_mode() -> None:
    set_json_mode(False)
    yield
    set_json_mode(False)


@pytest.fixture()
def ces_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    ces_dir = project_root / ".ces"
    ces_dir.mkdir(parents=True)
    (ces_dir / "config.yaml").write_text(
        "project_id: test-json-contract\nproject_name: JSON Contract Test\nexecution_mode: local\nversion: 1\n",
        encoding="utf-8",
    )
    return project_root


def _invoke(args: Sequence[str]) -> Any:
    return CliRunner().invoke(app, list(args))


def _parse_json_stdout(result: Any) -> Any:
    assert result.stdout.strip(), result.stderr
    assert not any(marker in result.stdout for marker in RICH_OR_ANSI_MARKERS)
    return json.loads(result.stdout)


def _assert_error_json(result: Any, *, expected_exit_code: int) -> dict[str, Any]:
    assert result.exit_code == expected_exit_code
    assert result.stdout == ""
    assert result.stderr.strip(), "expected machine-readable JSON error on stderr"
    assert not any(marker in result.stderr for marker in RICH_OR_ANSI_MARKERS)
    payload = json.loads(result.stderr)
    assert set(payload) == {"error"}
    assert payload["error"]["exit_code"] == expected_exit_code
    assert payload["error"]["message"]
    return payload


@pytest.mark.parametrize(
    ("root_args", "local_args", "expected_type"),
    [
        (("--json", "doctor"), ("doctor", "--json"), dict),
        (("--json", "status"), ("status", "--json"), dict),
        (("--json", "audit"), ("audit", "--json"), list),
    ],
)
def test_root_and_command_local_json_emit_valid_json(
    ces_project: Path,
    root_args: tuple[str, ...],
    local_args: tuple[str, ...],
    expected_type: type,
) -> None:
    root_result = _invoke([*root_args, "--project-root", str(ces_project)])
    local_result = _invoke([*local_args, "--project-root", str(ces_project)])

    assert root_result.exit_code in {0, 1}, root_result.stderr
    assert local_result.exit_code == root_result.exit_code

    root_payload = _parse_json_stdout(root_result)
    local_payload = _parse_json_stdout(local_result)
    assert isinstance(root_payload, expected_type)
    assert isinstance(local_payload, expected_type)
    if isinstance(root_payload, dict):
        assert root_payload.keys() == local_payload.keys()


def test_json_mode_does_not_leak_between_invocations(ces_project: Path) -> None:
    json_result = _invoke(["doctor", "--json", "--project-root", str(ces_project)])
    assert json_result.exit_code in {0, 1}
    _parse_json_stdout(json_result)

    rich_result = _invoke(["doctor", "--project-root", str(ces_project)])
    assert rich_result.exit_code in {0, 1}
    assert rich_result.stdout.strip()
    with pytest.raises(json.JSONDecodeError):
        json.loads(rich_result.stdout)


def test_root_json_handled_command_error_emits_error_json() -> None:
    result = _invoke(["--json", "doctor", "--runtime", "nope"])

    payload = _assert_error_json(result, expected_exit_code=1)
    assert payload["error"]["type"] == "user_error"
    assert "--runtime" in payload["error"]["message"]


def test_root_json_audit_validation_error_emits_error_json(ces_project: Path) -> None:
    result = _invoke(["--json", "audit", "--limit", "nope", "--project-root", str(ces_project)])

    payload = _assert_error_json(result, expected_exit_code=1)
    assert payload["error"]["type"] == "user_error"
    assert "--limit" in payload["error"]["message"]
