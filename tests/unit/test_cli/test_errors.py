"""Tests for CLI error handling (_errors module)."""

from __future__ import annotations

import json

import pytest
import typer

from ces.cli._errors import (
    EXIT_GOVERNANCE_VIOLATION,
    EXIT_SERVICE_ERROR,
    EXIT_USER_ERROR,
    GovernanceViolationError,
    handle_error,
)
from ces.cli._output import set_json_mode


@pytest.fixture(autouse=True)
def _reset_json_mode() -> None:
    set_json_mode(False)
    yield
    set_json_mode(False)


class TestExitCodeConstants:
    """Tests for exit code constant values."""

    def test_user_error_is_1(self) -> None:
        assert EXIT_USER_ERROR == 1

    def test_service_error_is_2(self) -> None:
        assert EXIT_SERVICE_ERROR == 2

    def test_governance_violation_is_3(self) -> None:
        assert EXIT_GOVERNANCE_VIOLATION == 3


class TestHandleError:
    """Tests for handle_error() exception-to-exit-code mapping."""

    def test_bad_parameter_exits_1(self) -> None:
        """typer.BadParameter maps to exit code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(typer.BadParameter("bad input"))
        assert exc_info.value.code == EXIT_USER_ERROR

    def test_value_error_exits_1(self) -> None:
        """ValueError maps to exit code 1 (user error)."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(ValueError("invalid value"))
        assert exc_info.value.code == EXIT_USER_ERROR

    def test_connection_error_exits_2(self) -> None:
        """ConnectionError maps to exit code 2 (service error)."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(ConnectionError("database unavailable"))
        assert exc_info.value.code == EXIT_SERVICE_ERROR

    def test_os_error_exits_2(self) -> None:
        """OSError maps to exit code 2 (service error)."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(OSError("file system error"))
        assert exc_info.value.code == EXIT_SERVICE_ERROR

    def test_governance_violation_exits_3(self) -> None:
        """GovernanceViolationError maps to exit code 3."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(GovernanceViolationError("manifest expired"))
        assert exc_info.value.code == EXIT_GOVERNANCE_VIOLATION

    def test_unknown_error_exits_1(self) -> None:
        """Unknown exceptions default to exit code 1."""
        with pytest.raises(SystemExit) as exc_info:
            handle_error(Exception("something unexpected"))
        assert exc_info.value.code == EXIT_USER_ERROR

    def test_json_mode_emits_machine_readable_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """In --json mode, handled errors emit a stable JSON payload to stderr."""
        set_json_mode(True)

        with pytest.raises(SystemExit) as exc_info:
            handle_error(ValueError("invalid value"))

        captured = capsys.readouterr()
        assert exc_info.value.code == EXIT_USER_ERROR
        assert captured.out == ""
        assert json.loads(captured.err) == {
            "error": {
                "type": "user_error",
                "title": "User Error",
                "message": "invalid value",
                "exit_code": EXIT_USER_ERROR,
            }
        }

    def test_json_mode_preserves_governance_exit_code(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Governance failures remain machine-readable and keep exit code 3."""
        set_json_mode(True)

        with pytest.raises(SystemExit) as exc_info:
            handle_error(GovernanceViolationError("manifest expired"))

        payload = json.loads(capsys.readouterr().err)
        assert exc_info.value.code == EXIT_GOVERNANCE_VIOLATION
        assert payload["error"]["type"] == "governance_violation"
        assert payload["error"]["title"] == "Governance Violation"
        assert payload["error"]["message"] == "manifest expired"
        assert payload["error"]["exit_code"] == EXIT_GOVERNANCE_VIOLATION

    def test_json_mode_service_error_payload(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Service failures keep the stable JSON envelope and exit code 2."""
        set_json_mode(True)

        with pytest.raises(SystemExit) as exc_info:
            handle_error(ConnectionError("database unavailable"))

        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert captured.out == ""
        assert exc_info.value.code == EXIT_SERVICE_ERROR
        assert payload == {
            "error": {
                "type": "service_error",
                "title": "Service Error",
                "message": "database unavailable",
                "exit_code": EXIT_SERVICE_ERROR,
            }
        }

    def test_json_mode_unknown_error_payload(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Unknown handled exceptions stay parseable and fail as user errors."""
        set_json_mode(True)

        with pytest.raises(SystemExit) as exc_info:
            handle_error(Exception("unexpected"))

        captured = capsys.readouterr()
        payload = json.loads(captured.err)
        assert captured.out == ""
        assert exc_info.value.code == EXIT_USER_ERROR
        assert payload == {
            "error": {
                "type": "error",
                "title": "Error",
                "message": "unexpected",
                "exit_code": EXIT_USER_ERROR,
            }
        }


class TestGovernanceViolationError:
    """Tests for GovernanceViolationError custom exception."""

    def test_is_exception_subclass(self) -> None:
        assert issubclass(GovernanceViolationError, Exception)

    def test_stores_message(self) -> None:
        err = GovernanceViolationError("kill switch activated")
        assert str(err) == "kill switch activated"
