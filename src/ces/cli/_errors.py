"""Exception-to-exit-code mapping with Rich error panels.

Maps exception types to CES exit codes:
- 1: User error (bad input, validation failure)
- 2: Service error (DB unreachable, filesystem failure)
- 3: Governance violation (expired manifest, kill switch)

Error messages are user-friendly Rich panels. Stack traces are
never shown to prevent information disclosure (T-06-03).

Exports:
    EXIT_USER_ERROR: Exit code 1.
    EXIT_SERVICE_ERROR: Exit code 2.
    EXIT_GOVERNANCE_VIOLATION: Exit code 3.
    GovernanceViolationError: Custom exception for governance violations.
    handle_error: Map an exception to a Rich panel and exit code.
"""

from __future__ import annotations

import json
import sys

import typer
from rich.panel import Panel

from ces.cli._output import console, is_json_mode

# ---------------------------------------------------------------------------
# Exit code constants
# ---------------------------------------------------------------------------

EXIT_USER_ERROR: int = 1
EXIT_SERVICE_ERROR: int = 2
EXIT_GOVERNANCE_VIOLATION: int = 3


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class GovernanceViolationError(Exception):
    """Raised when a governance rule is violated.

    Examples: expired manifest, kill switch activated, unapproved
    artifact promotion, missing evidence packet.
    """


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

# Exception types that map to service errors (exit code 2)
_SERVICE_ERROR_TYPES = (ConnectionError, RuntimeError, OSError)


def handle_error(exc: Exception) -> None:
    """Map an exception to a styled Rich panel and exit with the appropriate code.

    Categorises exceptions into three buckets:
    - **User errors** (exit 1): typer.BadParameter, ValueError, and
      any other uncategorised exception.
    - **Service errors** (exit 2): ConnectionError, RuntimeError, OSError.
    - **Governance violations** (exit 3): GovernanceViolationError.

    The panel shows a human-readable title and the exception message.
    No stack traces are displayed (T-06-03 mitigation).

    Args:
        exc: The exception to handle.

    Raises:
        SystemExit: Always raises SystemExit with the mapped code.
    """
    if isinstance(exc, GovernanceViolationError):
        title = "Governance Violation"
        error_type = "governance_violation"
        code = EXIT_GOVERNANCE_VIOLATION
    elif isinstance(exc, _SERVICE_ERROR_TYPES):
        title = "Service Error"
        error_type = "service_error"
        code = EXIT_SERVICE_ERROR
    elif isinstance(exc, (typer.BadParameter, ValueError)):
        title = "User Error"
        error_type = "user_error"
        code = EXIT_USER_ERROR
    else:
        title = "Error"
        error_type = "error"
        code = EXIT_USER_ERROR

    if is_json_mode():
        payload = {
            "error": {
                "type": error_type,
                "title": title,
                "message": str(exc),
                "exit_code": code,
            }
        }
        typer.echo(json.dumps(payload), err=True)
        sys.exit(code)

    console.print(
        Panel(
            str(exc),
            title=f"[red]{title}[/red]",
            border_style="red",
        )
    )
    sys.exit(code)
