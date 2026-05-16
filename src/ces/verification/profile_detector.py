"""Deterministic project verification profile detector."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from ces.verification.profile import PROFILE_RELATIVE_PATH, VerificationCheck, VerificationProfile, VerificationStatus

_DEP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def detect_verification_profile(project_root: str | Path) -> VerificationProfile:
    """Inspect project files and build a verification profile.

    The detector is intentionally conservative: configured pytest, ruff, mypy,
    and package.json checks are marked required because their artifacts should be
    present before completion. Coverage is marked advisory by default unless a
    human edits the profile to make it required.
    """
    root = Path(project_root)
    pyproject = _read_pyproject(root)
    package_json = _read_package_json(root)
    tool = pyproject.get("tool", {}) if isinstance(pyproject.get("tool", {}), dict) else {}
    deps = _flatten_dependencies(pyproject)
    scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts", {}), dict) else {}

    pytest_configured = "pytest" in tool or _deps_contain(deps, "pytest")
    ruff_configured = "ruff" in tool or _deps_contain(deps, "ruff")
    mypy_configured = "mypy" in tool or _deps_contain(deps, "mypy")
    coverage_configured = "coverage" in tool or _deps_contain(deps, "coverage") or _deps_contain(deps, "pytest-cov")

    checks = {
        "pytest": _configured_required("pytest", pytest_configured),
        "ruff": _configured_required("ruff", ruff_configured),
        "mypy": _configured_required("mypy", mypy_configured),
        "coverage": VerificationCheck(
            status=VerificationStatus.ADVISORY,
            configured=coverage_configured,
            reason=(
                "coverage configuration or dependency detected; coverage evidence is advisory by default"
                if coverage_configured
                else "coverage is not configured; coverage evidence is advisory by default"
            ),
        ),
    }
    if package_json:
        checks.update(
            {
                "node-test": _node_script_required("test", scripts),
                "node-build": _node_script_required("build", scripts),
                "node-typecheck": _node_script_required("typecheck", scripts),
                "node-lint": _node_script_required("lint", scripts),
            }
        )

    return VerificationProfile(version=1, checks=checks)


def write_verification_profile(project_root: str | Path, profile: VerificationProfile | None = None) -> Path:
    """Write ``profile`` (or a detected one) to ``.ces/verification-profile.json``."""
    root = Path(project_root)
    profile = profile or detect_verification_profile(root)
    path = root / PROFILE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(profile.to_json(), encoding="utf-8")
    return path


def _configured_required(name: str, configured: bool) -> VerificationCheck:
    if configured:
        return VerificationCheck(
            status=VerificationStatus.REQUIRED,
            configured=True,
            reason=f"{name} configuration or dependency detected",
        )
    return VerificationCheck(
        status=VerificationStatus.UNAVAILABLE,
        configured=False,
        reason=f"{name} configuration or dependency not detected",
    )


def _node_script_required(script_name: str, scripts: dict[str, Any]) -> VerificationCheck:
    configured = script_name in scripts
    if configured:
        return VerificationCheck(
            status=VerificationStatus.REQUIRED,
            configured=True,
            reason=f"package.json {script_name} script detected",
        )
    return VerificationCheck(
        status=VerificationStatus.UNAVAILABLE,
        configured=False,
        reason=f"package.json {script_name} script not detected",
    )


def _read_pyproject(root: Path) -> dict[str, Any]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _read_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _flatten_dependencies(pyproject: dict[str, Any]) -> list[str]:
    values: list[str] = []
    project = pyproject.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            values.extend(str(dep).lower() for dep in dependencies)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for deps in optional.values():
                if isinstance(deps, list):
                    values.extend(str(dep).lower() for dep in deps)

    dependency_groups = pyproject.get("dependency-groups", {})
    if isinstance(dependency_groups, dict):
        for deps in dependency_groups.values():
            if isinstance(deps, list):
                values.extend(str(dep).lower() for dep in deps)
    return values


def _deps_contain(deps: list[str], package: str) -> bool:
    package = package.lower().replace("_", "-")
    for dep in deps:
        match = _DEP_NAME_RE.match(dep)
        if match is None:
            continue
        name = match.group(1).lower().replace("_", "-")
        if name == package:
            return True
    return False
