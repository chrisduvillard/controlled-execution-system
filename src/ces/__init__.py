"""Controlled Execution System - Deterministic governance for AI agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("controlled-execution-system")
except PackageNotFoundError:  # pragma: no cover - source-tree fallback
    __version__ = "0.1.18"
