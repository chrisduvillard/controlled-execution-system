"""Deterministic read-only Project MRI scanner."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_SECRET_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|PASSWORD|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\b")
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".ces",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}
_TEXT_SUFFIXES = {".cfg", ".conf", ".env", ".ini", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
_SECRET_SCAN_SUFFIXES = {".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml"}
_SECRET_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "secrets.yaml",
    "secrets.yml",
    "secret.yaml",
    "secret.yml",
}
_CONTAINER_FILE = "Dock" + "erfile"
_COMPOSE_FILES = ("dock" + "er-compose.yml", "dock" + "er-compose.yaml")
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass(frozen=True)
class MriSignal:
    """A detected project-health signal."""

    name: str
    category: str
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "category": self.category, "evidence": self.evidence}


@dataclass(frozen=True)
class MriFinding:
    """A project risk finding with redacted evidence."""

    severity: str
    category: str
    title: str
    evidence: str
    recommendation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class ProjectMriReport:
    """Project MRI report ready for markdown or JSON rendering."""

    project_root: Path
    project_type: str
    maturity: str
    summary: str
    signals: tuple[MriSignal, ...]
    strongest_evidence: tuple[str, ...]
    risk_findings: tuple[MriFinding, ...]
    missing_readiness_signals: tuple[str, ...]
    recommended_next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "project_type": self.project_type,
            "maturity": self.maturity,
            "summary": self.summary,
            "signals": [signal.to_dict() for signal in self.signals],
            "strongest_evidence": list(self.strongest_evidence),
            "risk_findings": [finding.to_dict() for finding in self.risk_findings],
            "missing_readiness_signals": list(self.missing_readiness_signals),
            "recommended_next_actions": list(self.recommended_next_actions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# Project MRI",
            "",
            f"Project root: `{self.project_root}`",
            f"Maturity: **{self.maturity}**",
            f"Project type: `{self.project_type}`",
            "",
            "## Summary",
            "",
            self.summary,
            "",
            "## Detected project signals",
            "",
        ]
        lines.extend(_bullet(f"**{signal.name}** ({signal.category}) — {signal.evidence}" for signal in self.signals))
        lines.extend(["", "## Strongest evidence", ""])
        lines.extend(_bullet(self.strongest_evidence))
        lines.extend(["", "## Risk findings", ""])
        if self.risk_findings:
            lines.extend(
                _bullet(
                    f"**{finding.severity.upper()} / {finding.category}: {finding.title}** — {finding.evidence}. {finding.recommendation}"
                    for finding in self.risk_findings
                )
            )
        else:
            lines.append("- No material risks detected by the current deterministic scan.")
        lines.extend(["", "## Missing production-readiness signals", ""])
        lines.extend(_bullet(self.missing_readiness_signals))
        lines.extend(["", "## Recommended next CES actions", ""])
        lines.extend(_bullet(f"`{action}`" for action in self.recommended_next_actions))
        return "\n".join(lines).rstrip() + "\n"


def scan_project_mri(project_root: str | Path) -> ProjectMriReport:
    """Scan ``project_root`` without mutating it and return a Project MRI report."""

    root = Path(project_root).resolve()
    project_type = _detect_project_type(root)
    signals = _detect_signals(root, project_type)
    findings = _detect_risks(root)
    missing = _missing_readiness_signals(signals)
    maturity = _classify_maturity(signals, findings, missing)
    strongest = _strongest_evidence(signals)
    actions = _recommended_actions(signals, findings, missing)
    summary = _summary(maturity, project_type, signals, findings, missing)
    ordered_findings = tuple(
        sorted(findings, key=lambda finding: (_SEVERITY_ORDER[finding.severity], finding.category, finding.title))
    )
    return ProjectMriReport(
        project_root=root,
        project_type=project_type,
        maturity=maturity,
        summary=summary,
        signals=tuple(sorted(signals, key=lambda signal: (signal.category, signal.name, signal.evidence))),
        strongest_evidence=strongest,
        risk_findings=ordered_findings,
        missing_readiness_signals=tuple(sorted(missing)),
        recommended_next_actions=actions,
    )


def _detect_project_type(root: Path) -> str:
    if not root.exists():
        return "unknown"
    if (
        _is_regular_file(root / _CONTAINER_FILE)
        and not _is_regular_file(root / "pyproject.toml")
        and not _is_regular_file(root / "package.json")
    ):
        return "containerized-app"
    pyproject = root / "pyproject.toml"
    package_json = root / "package.json"
    if _is_regular_file(pyproject):
        payload = _read_toml(pyproject)
        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict) and scripts:
            return "python-cli"
        return "python-package"
    if _is_regular_file(package_json):
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
    if _looks_like_python_project(root):
        return "python-package"
    return "unknown"


def _detect_signals(root: Path, project_type: str) -> list[MriSignal]:
    signals = [MriSignal("project-type", "project", project_type)]
    files = {
        "pyproject.toml": ("project", "Python package metadata"),
        "uv.lock": ("dependency", "uv lockfile"),
        "requirements.txt": ("dependency", "pip requirements"),
        "package.json": ("project", "Node package metadata"),
        "package-lock.json": ("dependency", "npm lockfile"),
        "pnpm-lock.yaml": ("dependency", "pnpm lockfile"),
        "yarn.lock": ("dependency", "Yarn lockfile"),
        _CONTAINER_FILE: ("runtime", "container runtime image"),
        _COMPOSE_FILES[0]: ("runtime", "compose runtime file"),
        _COMPOSE_FILES[1]: ("runtime", "compose runtime file"),
        "Procfile": ("runtime", "Procfile runtime declaration"),
        "README.md": ("documentation", "README present"),
        ".ces/verification-profile.json": ("ces", "CES verification profile"),
        ".ces/config.yaml": ("ces", "CES project config"),
        ".ces/state.db": ("ces", "CES local state database"),
    }
    for relative, (category, evidence) in files.items():
        if _is_regular_file(root / relative):
            signals.append(MriSignal(relative, category, evidence))

    if _is_regular_dir(root / "tests"):
        test_files = _safe_rglob(root / "tests", "test_*.py") + _safe_rglob(root / "tests", "*_test.py")
        signals.append(
            MriSignal("tests-directory", "test", f"tests/ present with {len(test_files)} Python test file(s)")
        )
    pyproject = _read_toml(root / "pyproject.toml")
    package_json = _read_json(root / "package.json")
    signals.extend(_python_tool_signals(pyproject))
    signals.extend(_node_tool_signals(package_json, root))
    workflows_dir = root / ".github" / "workflows"
    workflows = _safe_glob(workflows_dir, "*.yml") + _safe_glob(workflows_dir, "*.yaml")
    if workflows:
        signals.append(MriSignal("github-actions", "ci", f"{len(workflows)} workflow file(s) under .github/workflows"))
    return signals


def _python_tool_signals(pyproject: dict[str, Any]) -> list[MriSignal]:
    tool = pyproject.get("tool", {}) if isinstance(pyproject.get("tool"), dict) else {}
    deps = _flatten_pyproject_dependencies(pyproject)
    signals: list[MriSignal] = []
    for name in ("pytest", "ruff", "mypy"):
        if name in tool or name in deps:
            category = "test" if name == "pytest" else "quality"
            signals.append(MriSignal(name, category, f"{name} configuration or dependency detected"))
    return signals


def _node_tool_signals(package_json: dict[str, Any], root: Path) -> list[MriSignal]:
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = package_json.get(key, {}) if isinstance(package_json, dict) else {}
        if isinstance(section, dict):
            deps.update(str(name) for name in section)
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    signals: list[MriSignal] = []
    if "eslint" in deps:
        signals.append(MriSignal("eslint", "quality", "eslint dependency detected"))
    if "typescript" in deps or _is_regular_file(root / "tsconfig.json"):
        signals.append(MriSignal("typescript", "quality", "TypeScript dependency or tsconfig detected"))
    if isinstance(scripts, dict) and "test" in scripts:
        signals.append(MriSignal("npm-test", "test", "package.json test script detected"))
    return signals


def _detect_risks(root: Path) -> list[MriFinding]:
    findings: list[MriFinding] = []
    if not _is_regular_file(root / "README.md"):
        findings.append(
            MriFinding(
                "medium",
                "maintainability",
                "Missing README",
                "README.md was not found",
                "Add a concise README before sharing the project",
            )
        )
    findings.extend(_secret_hygiene_findings(root))
    findings.extend(_maintainability_findings(root))
    return findings


def _secret_hygiene_findings(root: Path) -> list[MriFinding]:
    findings: list[MriFinding] = []
    for path in _iter_project_files(root):
        relative = path.relative_to(root).as_posix()
        if path.name in _SECRET_FILENAMES or path.name.endswith((".pem", ".key")):
            findings.append(
                MriFinding(
                    "high",
                    "secret-hygiene",
                    "Likely secret-bearing file present",
                    f"{relative} exists in the project tree",
                    "Ensure the file is untracked or contains only safe local placeholders",
                )
            )
        if path.suffix.lower() in _SECRET_SCAN_SUFFIXES or path.name.startswith(".env"):
            names = _secret_variable_names(path)
            if names:
                findings.append(
                    MriFinding(
                        "high",
                        "secret-hygiene",
                        "Secret-like variable names detected",
                        f"{relative} references {', '.join(names)}",
                        "Review secret handling and keep values out of committed config",
                    )
                )
    return findings


def _maintainability_findings(root: Path) -> list[MriFinding]:
    todo_count = 0
    large_files: list[str] = []
    for path in _iter_project_files(root):
        if path.suffix.lower() not in _TEXT_SUFFIXES and path.suffix.lower() != ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()
        todo_count += text.count("TODO") + text.count("FIXME")
        line_count = text.count("\n") + 1 if text else 0
        if line_count > 800:
            large_files.append(f"{relative} ({line_count} lines)")
    findings: list[MriFinding] = []
    if todo_count:
        findings.append(
            MriFinding(
                "low",
                "maintainability",
                "TODO/FIXME markers present",
                f"{todo_count} TODO/FIXME marker(s) detected",
                "Review whether these are release blockers or backlog items",
            )
        )
    if large_files:
        findings.append(
            MriFinding(
                "medium",
                "maintainability",
                "Very large source/config files detected",
                "; ".join(large_files[:5]),
                "Split large files or add targeted tests around risky areas",
            )
        )
    return findings


def _missing_readiness_signals(signals: list[MriSignal]) -> list[str]:
    names = {signal.name for signal in signals}
    missing: list[str] = []
    if "README.md" not in names:
        missing.append("README.md")
    if not ({"pytest", "npm-test", "tests-directory"} & names):
        missing.append("test signal")
    if not ({"ruff", "mypy", "eslint", "typescript"} & names):
        missing.append("lint/typecheck signal")
    if "github-actions" not in names:
        missing.append("CI workflow")
    if not ({_CONTAINER_FILE, *_COMPOSE_FILES, "Procfile"} & names):
        missing.append("deployment/runtime declaration")
    if ".ces/verification-profile.json" not in names:
        missing.append("CES verification profile")
    return missing


def _classify_maturity(signals: list[MriSignal], findings: list[MriFinding], missing: list[str]) -> str:
    names = {signal.name for signal in signals}
    has_tests = bool({"pytest", "npm-test", "tests-directory"} & names)
    has_quality = bool({"ruff", "mypy", "eslint", "typescript"} & names)
    has_ci = "github-actions" in names
    has_runtime = bool({_CONTAINER_FILE, *_COMPOSE_FILES, "Procfile"} & names)
    has_ces_state = bool({".ces/verification-profile.json", ".ces/config.yaml", ".ces/state.db"} & names)
    has_high_risk = any(finding.severity in {"critical", "high"} for finding in findings)
    if has_tests and has_quality and has_ci and has_runtime and has_ces_state and not has_high_risk:
        return "operated-product"
    if has_tests and has_quality and has_ci and not has_high_risk:
        return "production-candidate"
    if has_tests and (has_quality or has_ci):
        return "shareable-app"
    if {"pyproject.toml", "package.json", _CONTAINER_FILE} & names:
        return "local-app"
    if not missing:
        return "local-app"
    return "vibe-prototype"


def _strongest_evidence(signals: list[MriSignal]) -> tuple[str, ...]:
    priority = [
        "github-actions",
        "pytest",
        "npm-test",
        "ruff",
        "mypy",
        "eslint",
        "typescript",
        ".ces/verification-profile.json",
        _CONTAINER_FILE,
        "README.md",
    ]
    by_name = {signal.name: signal for signal in signals}
    evidence = [f"{name}: {by_name[name].evidence}" for name in priority if name in by_name]
    if not evidence:
        evidence = [f"{signal.name}: {signal.evidence}" for signal in signals[:5]]
    return tuple(evidence[:6])


def _recommended_actions(signals: list[MriSignal], findings: list[MriFinding], missing: list[str]) -> tuple[str, ...]:
    names = {signal.name for signal in signals}
    actions = ["ces doctor"]
    if ".ces/verification-profile.json" not in names:
        actions.append("ces profile detect --write")
    if "test signal" not in missing and "lint/typecheck signal" not in missing:
        actions.append("ces verify")
    else:
        actions.append('ces build "Add the missing verification/readiness signals reported by ces mri"')
    if any(finding.category == "secret-hygiene" for finding in findings):
        actions.append('ces build "Harden secret hygiene without committing secret values"')
    return tuple(actions)


def _summary(
    maturity: str, project_type: str, signals: list[MriSignal], findings: list[MriFinding], missing: list[str]
) -> str:
    risk_count = len([finding for finding in findings if finding.severity in {"critical", "high", "medium"}])
    return (
        f"This {project_type} currently looks like a {maturity}. "
        f"The scan found {len(signals)} signal(s), {risk_count} material risk finding(s), "
        f"and {len(missing)} missing production-readiness signal(s)."
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not _is_regular_file(path):
        return {}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not _is_regular_file(path):
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _looks_like_python_project(root: Path) -> bool:
    tests_dir = root / "tests"
    if _is_regular_dir(tests_dir) and _safe_rglob(tests_dir, "*.py"):
        return True
    try:
        children = sorted(root.iterdir(), key=lambda child: child.name)
    except OSError:
        return False
    for child in children:
        if child.name.startswith((".", "__")) or child.is_symlink():
            continue
        if _is_regular_file(child) and child.suffix == ".py":
            return True
        if _is_regular_dir(child) and (
            _is_regular_file(child / "__init__.py") or _is_regular_file(child / "__main__.py")
        ):
            return True
    return False


def _is_regular_file(path: Path) -> bool:
    return not _has_symlink_component(path) and path.is_file()


def _is_regular_dir(path: Path) -> bool:
    return not _has_symlink_component(path) and path.is_dir()


def _has_symlink_component(path: Path) -> bool:
    try:
        return any(part.is_symlink() for part in (path, *path.parents))
    except OSError:
        return True


def _safe_glob(root: Path, pattern: str) -> list[Path]:
    if not _is_regular_dir(root):
        return []
    return sorted(path for path in root.glob(pattern) if _is_regular_file(path))


def _safe_rglob(root: Path, pattern: str) -> list[Path]:
    if not _is_regular_dir(root):
        return []
    return sorted(path for path in root.rglob(pattern) if _is_regular_file(path))


def _flatten_pyproject_dependencies(pyproject: dict[str, Any]) -> set[str]:
    raw_values: list[str] = []
    project = pyproject.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            raw_values.extend(str(dep) for dep in dependencies)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for values in optional.values():
                if isinstance(values, list):
                    raw_values.extend(str(dep) for dep in values)
    groups = pyproject.get("dependency-groups", {})
    if isinstance(groups, dict):
        for values in groups.values():
            if isinstance(values, list):
                raw_values.extend(str(dep) for dep in values)
    names: set[str] = set()
    for value in raw_values:
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)", value)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def _secret_variable_names(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if path.suffix.lower() == ".json":
        return _secret_json_keys(text)
    return _secret_assignment_keys(text)


def _secret_json_keys(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    keys: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                if _SECRET_NAME_RE.fullmatch(key_text):
                    keys.add(key_text)
                visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return sorted(keys)[:10]


def _secret_assignment_keys(text: str) -> list[str]:
    keys: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        key = _assignment_key(line)
        if key and _SECRET_NAME_RE.fullmatch(key):
            keys.add(key)
    return sorted(keys)[:10]


def _assignment_key(line: str) -> str | None:
    for separator in ("=", ":"):
        if separator not in line:
            continue
        key = line.split(separator, 1)[0].strip().strip("\"'")
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        return key or None
    return None


def _iter_project_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    root = root.resolve()
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _bullet(items: Any) -> list[str]:
    values = list(items)
    if not values:
        return ["- None detected."]
    return [f"- {item}" for item in values]
