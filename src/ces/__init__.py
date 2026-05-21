"""Controlled Execution System - Deterministic governance for AI agents."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _source_tree_version() -> str:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            try:
                return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
            except (KeyError, OSError, tomllib.TOMLDecodeError):
                break
    return "0+unknown"


try:
    __version__ = version("controlled-execution-system")
except PackageNotFoundError:  # pragma: no cover - source-tree fallback
    __version__ = _source_tree_version()
