"""Deterministic read-only Project MRI scanner."""

from __future__ import annotations

import json
import re
import shlex
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
_MATURITY_LADDER = ("vibe-prototype", "local-app", "shareable-app", "production-candidate", "production-ready")
_READINESS_CATEGORIES = {
    "project": 10,
    "documentation": 10,
    "tests": 20,
    "quality": 15,
    "ci": 20,
    "runtime": 15,
    "ces": 10,
}


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
    readiness_score: dict[str, Any]
    maturity_ladder: tuple[str, ...]
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
            "readiness_score": self.readiness_score,
            "maturity_ladder": list(self.maturity_ladder),
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
            f"Readiness score: **{self.readiness_score['score']}/{self.readiness_score['max_score']}**",
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
        readiness_score=_readiness_score(signals),
        maturity_ladder=_MATURITY_LADDER,
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
        deps = _flatten_pyproject_dependencies(payload)
        if {"fastapi", "uvicorn"} & deps:
            return "fastapi-app"
        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict) and scripts:
            return "python-cli"
        return "python-package"
    if _is_regular_file(package_json):
        payload = _read_json(package_json)
        node_deps: dict[str, Any] = {}
        for key in ("dependencies", "devDependencies"):
            section = payload.get(key, {}) if isinstance(payload, dict) else {}
            if isinstance(section, dict):
                node_deps.update(section)
        scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
        if "react" in node_deps and ("vite" in node_deps or "@vitejs/plugin-react" in node_deps or "build" in scripts):
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
    findings.extend(_ai_slop_findings(root))
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


def _ai_slop_findings(root: Path) -> list[MriFinding]:
    weak_tests: list[str] = []
    exception_swallowers: list[str] = []
    generated_clutter: list[str] = []
    for path in _iter_project_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.endswith((".min.js", ".bundle.js")) or path.name in {"package-lock.json", "yarn.lock"}:
            generated_clutter.append(relative)
        if path.suffix.lower() != ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "/tests/" in f"/{relative}" or path.name.startswith("test_") or path.name.endswith("_test.py"):
            if "assert " not in text and "pytest.raises" not in text and "unittest" not in text:
                weak_tests.append(relative)
        if re.search(r"except\s+Exception\s*:\s*(?:\n\s*)pass\b", text):
            exception_swallowers.append(relative)
    findings: list[MriFinding] = []
    if weak_tests:
        findings.append(
            MriFinding(
                "medium",
                "ai-slop",
                "Assertion-free or trivial tests detected",
                "; ".join(weak_tests[:5]),
                "Add behavioral assertions that would fail if the implementation regresses",
            )
        )
    if exception_swallowers:
        findings.append(
            MriFinding(
                "high",
                "ai-slop",
                "Broad exception swallowing detected",
                "; ".join(exception_swallowers[:5]),
                "Handle specific exceptions and preserve actionable errors",
            )
        )
    if len(generated_clutter) > 4:
        findings.append(
            MriFinding(
                "low",
                "ai-slop",
                "Generated artifact clutter detected",
                f"{len(generated_clutter)} generated-looking artifact(s)",
                "Confirm generated artifacts are intentionally tracked or ignored",
            )
        )
    return findings


def _readiness_score(signals: list[MriSignal]) -> dict[str, Any]:
    names = {signal.name for signal in signals}
    passed: list[str] = []
    if {"pyproject.toml", "package.json", _CONTAINER_FILE, "project-type"} & names:
        passed.append("project")
    if "README.md" in names:
        passed.append("documentation")
    if {"pytest", "npm-test", "tests-directory"} & names:
        passed.append("tests")
    if {"ruff", "mypy", "eslint", "typescript"} & names:
        passed.append("quality")
    if "github-actions" in names:
        passed.append("ci")
    if {_CONTAINER_FILE, *_COMPOSE_FILES, "Procfile"} & names:
        passed.append("runtime")
    if {".ces/verification-profile.json", ".ces/config.yaml", ".ces/state.db"} & names:
        passed.append("ces")
    passed = sorted(passed)
    missing = sorted(category for category in _READINESS_CATEGORIES if category not in passed)
    return {
        "score": sum(_READINESS_CATEGORIES[category] for category in passed),
        "max_score": sum(_READINESS_CATEGORIES.values()),
        "passed": passed,
        "missing": missing,
    }


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
        return "production-ready"
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


@dataclass(frozen=True)
class NextActionReport:
    project_root: Path
    current_maturity: str
    target_maturity: str
    highest_priority_blockers: tuple[str, ...]
    recommended_command: str
    feature_work_guidance: str
    readiness_score: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "current_maturity": self.current_maturity,
            "target_maturity": self.target_maturity,
            "highest_priority_blockers": list(self.highest_priority_blockers),
            "recommended_command": self.recommended_command,
            "feature_work_guidance": self.feature_work_guidance,
            "readiness_score": self.readiness_score,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        return (
            "\n".join(
                [
                    "# Next Production-Readiness Step",
                    "",
                    f"Project root: `{self.project_root}`",
                    f"Current maturity: **{self.current_maturity}**",
                    f"Target maturity: **{self.target_maturity}**",
                    f"Recommended command: `{self.recommended_command}`",
                    "",
                    "## Highest-priority blockers",
                    "",
                    *_bullet(self.highest_priority_blockers),
                    "",
                    "## Feature-work guidance",
                    "",
                    self.feature_work_guidance,
                ]
            ).rstrip()
            + "\n"
        )


@dataclass(frozen=True)
class NextPromptReport:
    next_action: NextActionReport
    prompt: str
    validation_commands: tuple[str, ...]
    non_goals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "next_action": self.next_action.to_dict(),
            "prompt": self.prompt,
            "validation_commands": list(self.validation_commands),
            "non_goals": list(self.non_goals),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        return self.prompt.rstrip() + "\n"


@dataclass(frozen=True)
class ShipPlanReport:
    """Read-only beginner front-door plan from idea to proof-backed project."""

    project_root: Path
    objective: str | None
    execution_mode: str
    current_maturity: str
    target_maturity: str
    readiness_score: dict[str, Any]
    blockers: tuple[str, ...]
    recommended_command: str
    recommended_commands: tuple[str, ...]
    next_prompt: str
    safety_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "objective": self.objective,
            "execution_mode": self.execution_mode,
            "current_maturity": self.current_maturity,
            "target_maturity": self.target_maturity,
            "readiness_score": self.readiness_score,
            "blockers": list(self.blockers),
            "recommended_command": self.recommended_command,
            "recommended_commands": list(self.recommended_commands),
            "next_prompt": self.next_prompt,
            "safety_notes": list(self.safety_notes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        objective = self.objective or "No objective supplied yet."
        return (
            "\n".join(
                [
                    "# CES Ship Plan",
                    "",
                    f"Project root: `{self.project_root}`",
                    f"Objective: {objective}",
                    f"Execution mode: **{self.execution_mode}**",
                    f"Current maturity: **{self.current_maturity}**",
                    f"Target maturity: **{self.target_maturity}**",
                    f"Recommended command: `{self.recommended_command}`",
                    "",
                    "## What this command does",
                    "",
                    "This is a read-only plan. It does not launch Codex or Claude Code, does not create `.ces/`, and does not edit project files.",
                    "",
                    "## Highest-priority blockers",
                    "",
                    *_bullet(self.blockers),
                    "",
                    "## Recommended command sequence",
                    "",
                    *_bullet(f"`{command}`" for command in self.recommended_commands),
                    "",
                    "## Safety notes",
                    "",
                    *_bullet(self.safety_notes),
                    "",
                    "## Guardrailed next prompt",
                    "",
                    self.next_prompt,
                ]
            ).rstrip()
            + "\n"
        )


@dataclass(frozen=True)
class ProductionPassportReport:
    report: ProjectMriReport
    evidence_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        score = self.report.readiness_score
        findings = [finding.to_dict() for finding in self.report.risk_findings]
        blockers = [
            finding.to_dict() for finding in self.report.risk_findings if finding.severity in {"critical", "high"}
        ]
        warnings = [
            finding.to_dict() for finding in self.report.risk_findings if finding.severity in {"medium", "low", "info"}
        ]
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.report.project_root),
            "detected_archetype": self.report.project_type,
            "maturity_level": self.report.maturity,
            "readiness_score": score,
            "passed_signals": [signal.to_dict() for signal in self.report.signals],
            "blockers": blockers,
            "warnings": warnings,
            "risk_findings": findings,
            "missing_production_readiness_signals": list(self.report.missing_readiness_signals),
            "recommended_next_promotion": _next_maturity(self.report.maturity),
            "evidence_sources": list(self.evidence_sources),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        payload = self.to_dict()
        blockers = payload["blockers"]
        if blockers:
            blocker_lines = _bullet(f"{item['severity']}: {item['title']} — {item['evidence']}" for item in blockers)
        elif payload["missing_production_readiness_signals"]:
            blocker_lines = [
                "- No critical/high blockers detected.",
                "- Readiness is incomplete; see missing production-readiness signals below.",
            ]
        else:
            blocker_lines = ["- No critical/high blockers detected."]
        return (
            "\n".join(
                [
                    "# Production Passport",
                    "",
                    f"Project root: `{payload['project_root']}`",
                    f"Detected archetype: `{payload['detected_archetype']}`",
                    f"Maturity level: **{payload['maturity_level']}**",
                    f"Readiness score: **{payload['readiness_score']['score']}/{payload['readiness_score']['max_score']}**",
                    f"Recommended next promotion: `{payload['recommended_next_promotion']}`",
                    "",
                    "## Blockers",
                    "",
                    *blocker_lines,
                    "",
                    "## Missing production-readiness signals",
                    "",
                    *_bullet(payload["missing_production_readiness_signals"]),
                    "",
                    "## Evidence sources",
                    "",
                    *_bullet(payload["evidence_sources"]),
                ]
            ).rstrip()
            + "\n"
        )


@dataclass(frozen=True)
class PromotionStep:
    target_maturity: str
    objective: str
    rationale: str
    suggested_prompt: str
    validation_commands: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_maturity": self.target_maturity,
            "objective": self.objective,
            "rationale": self.rationale,
            "suggested_prompt": self.suggested_prompt,
            "validation_commands": list(self.validation_commands),
            "stop_conditions": list(self.stop_conditions),
        }


@dataclass(frozen=True)
class PromotionPlanReport:
    project_root: Path
    current_maturity: str
    target_level: str
    execution_mode: str
    steps: tuple[PromotionStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "current_maturity": self.current_maturity,
            "target_level": self.target_level,
            "execution_mode": self.execution_mode,
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# Promotion Plan",
            "",
            f"Project root: `{self.project_root}`",
            f"Current maturity: **{self.current_maturity}**",
            f"Target level: **{self.target_level}**",
            f"Execution mode: `{self.execution_mode}`",
        ]
        for index, step in enumerate(self.steps, start=1):
            lines.extend(
                [
                    "",
                    f"## Step {index}: {step.target_maturity}",
                    "",
                    step.objective,
                    "",
                    f"Rationale: {step.rationale}",
                    "",
                    "Suggested prompt:",
                    "",
                    f"```text\n{step.suggested_prompt}\n```",
                    "",
                    "Validation commands:",
                    "",
                    *_bullet(step.validation_commands),
                ]
            )
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class Invariant:
    text: str
    source: str
    category: str

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "source": self.source, "category": self.category}


@dataclass(frozen=True)
class InvariantsReport:
    project_root: Path
    invariants: tuple[Invariant, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "invariants": [invariant.to_dict() for invariant in self.invariants],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        return (
            "\n".join(
                ["# Project Invariants", "", *_bullet(f"{item.text} ({item.source})" for item in self.invariants)]
            ).rstrip()
            + "\n"
        )


@dataclass(frozen=True)
class RehearsalCommand:
    command: str
    category: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"command": self.command, "category": self.category, "reason": self.reason}


@dataclass(frozen=True)
class LaunchRehearsalReport:
    project_root: Path
    mode: str
    commands: tuple[RehearsalCommand, ...]
    skipped: tuple[str, ...]

    @property
    def recommended_commands(self) -> tuple[str, ...]:
        return tuple(command.command for command in self.commands)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "mode": self.mode,
            "commands": [command.to_dict() for command in self.commands],
            "recommended_commands": list(self.recommended_commands),
            "skipped": list(self.skipped),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    def to_markdown(self) -> str:
        return (
            "\n".join(
                [
                    "# Launch Rehearsal",
                    "",
                    f"Project root: `{self.project_root}`",
                    f"Mode: `{self.mode}`",
                    "",
                    "## Recommended commands",
                    "",
                    *_bullet(f"`{command.command}` — {command.reason}" for command in self.commands),
                    "",
                    "## Skipped",
                    "",
                    *_bullet(self.skipped),
                ]
            ).rstrip()
            + "\n"
        )


def build_next_action(project_root: str | Path) -> NextActionReport:
    report = scan_project_mri(project_root)
    target = _next_maturity(report.maturity)
    blockers = _highest_priority_blockers(report)
    command = _command_for_missing(report)
    guidance = (
        "Pause feature work until high-risk blockers are cleared."
        if any(f.severity in {"critical", "high"} for f in report.risk_findings)
        else "Feature work can continue only if it also closes the next readiness gap."
    )
    return NextActionReport(
        report.project_root, report.maturity, target, blockers, command, guidance, report.readiness_score
    )


def build_next_prompt(project_root: str | Path) -> NextPromptReport:
    action = build_next_action(project_root)
    validation = _validation_commands_for(scan_project_mri(project_root))
    non_goals = (
        "Do not add hosted services, dashboards, deployment platforms, or network calls.",
        "Do not weaken CES governance, approval, evidence, redaction, or consent gates.",
        "Do not print or commit secret values.",
    )
    prompt = "\n".join(
        [
            "# Next Production-Readiness Prompt",
            "",
            "Objective:",
            f"Move this project from `{action.current_maturity}` toward `{action.target_maturity}` by completing the next safest production-readiness step.",
            "",
            "Scope:",
            *_bullet(action.highest_priority_blockers),
            "",
            "Files/areas to inspect:",
            *_bullet(
                (
                    "README/docs",
                    "project config",
                    "tests",
                    "CI/quality configuration",
                    ".ces verification policy if present",
                )
            ),
            "",
            "Validation commands:",
            *_bullet(validation),
            "",
            "Non-goals:",
            *_bullet(non_goals),
            "",
            "Secret-handling rule:",
            "Report only secret filenames, key names, or categories. Never print secret values.",
            "",
            "Completion evidence:",
            "Summarize files changed, readiness gap closed, commands run, exact results, and remaining blockers.",
            "",
            f"Recommended CES command after implementation: `{action.recommended_command}`",
        ]
    )
    return NextPromptReport(action, prompt, validation, non_goals)


def build_production_passport(project_root: str | Path) -> ProductionPassportReport:
    report = scan_project_mri(project_root)
    sources = ["deterministic project scan"]
    if any(signal.name.startswith(".ces/") for signal in report.signals):
        sources.append("local CES evidence/state signals")
    return ProductionPassportReport(report, tuple(sources))


def build_ship_plan(project_root: str | Path, objective: str | None = None) -> ShipPlanReport:
    """Build a read-only beginner plan for getting from idea to proof-backed delivery."""

    action = build_next_action(project_root)
    prompt = build_next_prompt(project_root)
    objective_text = objective.strip() if objective and objective.strip() else None
    report = scan_project_mri(project_root)
    greenfield_command = _greenfield_command(objective_text)
    is_greenfield = _is_greenfield_report(report)
    recommended = greenfield_command if is_greenfield else action.recommended_command
    commands = ["ces doctor"]
    if is_greenfield:
        if objective_text:
            commands.append(greenfield_command)
        else:
            commands.append(
                'ces build --from-scratch "Describe the app you want to create, including tests and run instructions"'
            )
    else:
        commands.extend(["ces mri", "ces next", "ces next-prompt"])
        if recommended != "ces verify":
            commands.append(recommended)
    commands.extend(["ces passport", "ces launch rehearsal"])
    safety_notes = (
        "`ces ship` is read-only; it plans the path and explains the next command before any runtime launch.",
        "`ces build --from-scratch` may ask for explicit runtime side-effect consent before launching Codex or Claude Code.",
        "Keep secrets out of prompts and commits; report only secret names, files, or categories.",
    )
    return ShipPlanReport(
        project_root=action.project_root,
        objective=objective_text,
        execution_mode="read-only-plan",
        current_maturity=action.current_maturity,
        target_maturity=action.target_maturity,
        readiness_score=action.readiness_score,
        blockers=action.highest_priority_blockers,
        recommended_command=recommended,
        recommended_commands=tuple(commands),
        next_prompt=prompt.prompt,
        safety_notes=safety_notes,
    )


def build_promotion_plan(project_root: str | Path, target_level: str) -> PromotionPlanReport:
    if target_level not in {"shareable-app", "production-candidate", "production-ready"}:
        raise ValueError("target level must be shareable-app, production-candidate, or production-ready")
    report = scan_project_mri(project_root)
    current_index = _MATURITY_LADDER.index(report.maturity)
    target_index = _MATURITY_LADDER.index(target_level)
    levels = _MATURITY_LADDER[current_index + 1 : target_index + 1] if target_index > current_index else (target_level,)
    steps = tuple(
        PromotionStep(
            target_maturity=level,
            objective=f"Close the next readiness gaps needed for `{level}`.",
            rationale="Promotion is planned one maturity checkpoint at a time to avoid unsafe broad rewrites.",
            suggested_prompt=build_next_prompt(project_root).prompt,
            validation_commands=_validation_commands_for(report),
            stop_conditions=(
                "A high-risk finding appears",
                "Validation fails",
                "The next maturity checkpoint is reached",
            ),
        )
        for level in levels
    )
    return PromotionPlanReport(report.project_root, report.maturity, target_level, "plan-only", steps)


def mine_project_invariants(project_root: str | Path) -> InvariantsReport:
    root = Path(project_root).resolve()
    invariants: list[Invariant] = []
    for relative in ("README.md", "docs/README.md"):
        path = root / relative
        if not _is_regular_file(path):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip().strip("- ")
            lowered = line.lower()
            if lowered.startswith(
                ("safety invariant:", "public boundary:", "verification policy:", "security invariant:")
            ):
                category = line.split(":", 1)[0].lower().replace(" ", "-")
                invariants.append(Invariant(line, f"{relative}:{line_number}", category))
    return InvariantsReport(root, tuple(sorted(invariants, key=lambda item: (item.text, item.source))))


def build_launch_rehearsal(project_root: str | Path) -> LaunchRehearsalReport:
    report = scan_project_mri(project_root)
    root = report.project_root
    commands: list[RehearsalCommand] = []
    names = {signal.name for signal in report.signals}
    if "pyproject.toml" in names:
        if "tests-directory" in names or "pytest" in names:
            commands.append(
                RehearsalCommand(
                    "uv run pytest tests/ -q", "recommended", "Run local tests without changing project files"
                )
            )
        if {"ruff", "mypy"} & names:
            commands.append(RehearsalCommand("uv run ruff check .", "recommended", "Check Python lint/quality signals"))
        if "mypy" in names:
            commands.append(
                RehearsalCommand("uv run mypy . --ignore-missing-imports", "recommended", "Check type-readiness signal")
            )
    if "package.json" in names:
        commands.append(
            RehearsalCommand(
                "npm test", "recommended", "Run configured Node test command if dependencies are installed"
            )
        )
    if not commands:
        commands.append(RehearsalCommand("ces mri --format json", "smoke", "Re-run deterministic readiness scan"))
    skipped = ("Clean checkout rehearsal is not run by MVP mode; this command emits a read-only plan.",)
    return LaunchRehearsalReport(root, "read-only-plan", tuple(commands), skipped)


def build_slop_scan(project_root: str | Path) -> dict[str, Any]:
    report = scan_project_mri(project_root)
    findings = [finding.to_dict() for finding in report.risk_findings if finding.category == "ai-slop"]
    return {"schema_version": _SCHEMA_VERSION, "project_root": str(report.project_root), "findings": findings}


def _next_maturity(current: str) -> str:
    try:
        index = _MATURITY_LADDER.index(current)
    except ValueError:
        return "local-app"
    return _MATURITY_LADDER[min(index + 1, len(_MATURITY_LADDER) - 1)]


def _highest_priority_blockers(report: ProjectMriReport) -> tuple[str, ...]:
    blockers = [
        f"{finding.severity}: {finding.title} — {finding.evidence}"
        for finding in report.risk_findings
        if finding.severity in {"critical", "high"}
    ]
    if blockers:
        return tuple(blockers[:5])
    if report.missing_readiness_signals:
        return tuple(report.missing_readiness_signals[:5])
    return ("No immediate blocker detected by deterministic scan; preserve current readiness while validating.",)


def _command_for_missing(report: ProjectMriReport) -> str:
    if any(finding.category == "secret-hygiene" for finding in report.risk_findings):
        return 'ces build "Harden secret hygiene without committing secret values"'
    if _is_greenfield_report(report):
        return _greenfield_command(None)
    if report.missing_readiness_signals:
        return 'ces build "Add the next missing production-readiness signal reported by ces next"'
    return "ces verify"


def _is_greenfield_report(report: ProjectMriReport) -> bool:
    signal_names = {signal.name for signal in report.signals}
    return report.project_type == "unknown" and signal_names <= {"project-type"}


def _greenfield_command(objective: str | None) -> str:
    request = objective or "Create a small runnable app with README, tests, and run instructions"
    return f"ces build --from-scratch {shlex.quote(request)}"


def _validation_commands_for(report: ProjectMriReport) -> tuple[str, ...]:
    names = {signal.name for signal in report.signals}
    commands = ["ces mri --format json"]
    if "pyproject.toml" in names:
        if "tests-directory" in names or "pytest" in names:
            commands.append("uv run pytest tests/ -q")
        if {"ruff", "mypy"} & names:
            commands.append("uv run ruff check .")
        if "mypy" in names:
            commands.append("uv run mypy . --ignore-missing-imports")
    if "package.json" in names:
        commands.append("npm test")
    return tuple(commands)


def _bullet(items: Any) -> list[str]:
    values = list(items)
    if not values:
        return ["- None detected."]
    return [f"- {item}" for item in values]
