"""Project root detection and project context for CES CLI.

Walks up the directory tree from the current (or given) directory
to find the .ces/ marker that indicates a CES project root.

Exports:
    find_project_root: Locate the CES project root directory.
    get_project_id: Read the active project_id from .ces/config.yaml.
    get_project_config: Read the project config dictionary.
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml


def find_project_root(start: Path | None = None) -> Path:
    """Find the CES project root by looking for a .ces/ directory.

    Walks up from *start* (defaulting to cwd) through all parent
    directories.  Returns the first directory that contains a ``.ces/``
    subdirectory.

    Args:
        start: Directory to start searching from.  Defaults to the
            current working directory.

    Returns:
        Resolved Path to the project root.

    Raises:
        typer.BadParameter: If no .ces/ directory is found in any
            ancestor directory.
    """
    current = (start or Path.cwd()).resolve()

    for directory in [current, *current.parents]:
        if (directory / ".ces").is_dir():
            return directory

    raise typer.BadParameter("Not inside a CES project. Run 'ces init' first.")


def get_project_id(start: Path | None = None) -> str:
    """Read the active project_id from .ces/config.yaml.

    Falls back to 'default' if the config file or project_id key
    is missing (backwards compatibility with pre-v1.2 projects).

    Args:
        start: Directory to start searching from. Defaults to cwd.

    Returns:
        The project_id string.
    """
    root = find_project_root(start)
    config_path = root / ".ces" / "config.yaml"
    if config_path.is_file():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            return config.get("project_id", "default")
        except (OSError, yaml.YAMLError):
            pass
    return "default"


def get_project_config(start: Path | None = None) -> dict:
    """Read the full CES project config from `.ces/config.yaml`."""
    root = find_project_root(start)
    config_path = root / ".ces" / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
