"""Helpers for migrating legacy CES configurations to the local-first product.

The published CES product is the local builder-first workflow; the previous
``execution_mode: server`` mode (FastAPI + Celery + Postgres) is no longer
supported. This module provides a single source of truth for detecting the
legacy mode and rejecting it with a consistent, actionable error.
"""

from __future__ import annotations

from typing import Mapping

_SERVER_MODE_REMOVAL_MESSAGE = (
    "CES server mode is no longer supported. "
    "Remove `execution_mode: server` from `.ces/config.yaml` "
    "and use the local builder-first workflow."
)


def reject_server_mode(project_config: Mapping[str, object]) -> None:
    """Raise ``RuntimeError`` if the project config still requests server mode."""
    if project_config.get("execution_mode") == "server":
        raise RuntimeError(_SERVER_MODE_REMOVAL_MESSAGE)
