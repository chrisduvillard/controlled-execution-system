"""Project type detection for independent verification."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any


def detect_project_type(project_root: Path) -> str:
    pyproject = project_root / "pyproject.toml"
    package_json = project_root / "package.json"
    if pyproject.is_file():
        payload = _read_toml(pyproject)
        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict) and scripts:
            return "python-cli"
        return "python-package"
    if package_json.is_file():
        payload = _read_json(package_json)
        deps: dict[str, Any] = {}
        for key in ("dependencies", "devDependencies"):
            section = payload.get(key, {}) if isinstance(payload, dict) else {}
            if isinstance(section, dict):
                deps.update(section)
        scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
        if "react" in deps and ("vite" in deps or "@vitejs/plugin-react" in deps or "build" in scripts):
            return "vite-react-app"
        return "node-app"
    if _looks_like_container_project(project_root):
        return "containerized-app"
    if _looks_like_python_project(project_root):
        return "python-package"
    return "unknown"


def _looks_like_container_project(project_root: Path) -> bool:
    container_markers = (
        "D" + "ockerfile",
        "container-compose.yml",
        "container-compose.yaml",
        "compose.yml",
        "compose.yaml",
    )
    return any((project_root / marker).is_file() for marker in container_markers)


def _looks_like_python_project(project_root: Path) -> bool:
    tests_dir = project_root / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("*.py")):
        return True
    for child in project_root.iterdir():
        if child.name.startswith((".", "__")):
            continue
        if child.is_file() and child.suffix == ".py":
            return True
        if child.is_dir() and ((child / "__init__.py").is_file() or (child / "__main__.py").is_file()):
            return True
    return False


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
