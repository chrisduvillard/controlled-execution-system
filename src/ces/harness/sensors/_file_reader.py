"""Safe file reading utility for sensors.

Provides shared helpers for reading project files from the sensor context.
Handles missing files, permission errors, and oversized files gracefully.
"""

from __future__ import annotations

from pathlib import Path

#: Maximum file size to read (1 MB).
MAX_FILE_SIZE = 1_048_576


def read_file_safe(project_root: str, relative_path: str, max_size: int = MAX_FILE_SIZE) -> str | None:
    """Read a file safely, returning None if not found or too large.

    Args:
        project_root: Absolute path to the project root directory.
        relative_path: Path relative to project_root.
        max_size: Maximum file size in bytes to read.

    Returns:
        File contents as string, or None if the file cannot be read.
    """
    if not project_root:
        return None
    root = Path(project_root).resolve()
    path = (root / relative_path).resolve()
    # Prevent path traversal outside project root
    if not path.is_relative_to(root):
        return None
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_size:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def filter_by_extension(files: list[str], extensions: tuple[str, ...]) -> list[str]:
    """Filter file paths by extension.

    Args:
        files: List of file paths to filter.
        extensions: Tuple of extensions to match (e.g., (".py", ".pyx")).

    Returns:
        Filtered list of paths ending with one of the extensions.
    """
    return [f for f in files if f.endswith(extensions)]
