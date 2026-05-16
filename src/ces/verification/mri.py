"""Deterministic read-only Project MRI scanner."""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ces.execution.pipeline import COMPLETION_CLAIM_INSTRUCTIONS
from ces.intent_gate.classifier import classify_intent
from ces.verification.command_inference import _node_package_manager, _node_run_command

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
_CES_RUNTIME_DECLARATION_SIGNAL = "ces-runtime-declaration"
_CES_COMPLETION_CONTRACT_SIGNAL = ".ces/completion-contract.json"
_RUNTIME_SIGNAL_NAMES = frozenset({_CONTAINER_FILE, *_COMPOSE_FILES, "Procfile", _CES_RUNTIME_DECLARATION_SIGNAL})
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
_OBJECTIVE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "change",
        "current",
        "existing",
        "feature",
        "for",
        "from",
        "in",
        "into",
        "keep",
        "make",
        "new",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "update",
        "with",
    }
)
_OBJECTIVE_HINT_EXCLUDED_PREFIXES = (
    "docs/audits/",
    "docs/historical/",
    "docs/plans/",
    "tests/fixtures/",
    "tests/integration/_compat/",
)
_RUNTIME_OBJECTIVE_TOKENS = frozenset({"deploy", "deployment", "entrypoint", "procfile", "runtime"})
_TEST_OBJECTIVE_TOKENS = frozenset({"coverage", "mypy", "pytest", "ruff", "test", "tests", "typecheck", "verify"})


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
        "bun.lock": ("dependency", "Bun lockfile"),
        "bun.lockb": ("dependency", "Bun lockfile"),
        "pnpm-lock.yaml": ("dependency", "pnpm lockfile"),
        "yarn.lock": ("dependency", "Yarn lockfile"),
        _CONTAINER_FILE: ("runtime", "container runtime image"),
        _COMPOSE_FILES[0]: ("runtime", "compose runtime file"),
        _COMPOSE_FILES[1]: ("runtime", "compose runtime file"),
        "Procfile": ("runtime", "Procfile runtime declaration"),
        "README.md": ("documentation", "README present"),
        _CES_COMPLETION_CONTRACT_SIGNAL: ("ces", "CES completion contract with verification commands"),
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
    runtime_declaration = _runtime_declaration_signal(pyproject, package_json)
    if runtime_declaration is not None:
        signals.append(runtime_declaration)
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


def _runtime_declaration_signal(pyproject: dict[str, Any], package_json: dict[str, Any]) -> MriSignal | None:
    declaration = _runtime_declaration_from_pyproject(pyproject) or _runtime_declaration_from_package_json(package_json)
    entrypoint = str(declaration.get("entrypoint", "")).strip()
    if not entrypoint:
        return None
    kind = str(declaration.get("kind", "")).strip() or "unspecified"
    smoke_test = str(declaration.get("smoke_test", "")).strip()
    guide = str(declaration.get("deployment_guide", "")).strip()
    evidence_parts = [f"{kind} entrypoint `{entrypoint}`"]
    if smoke_test:
        evidence_parts.append(f"smoke `{smoke_test}`")
    if guide:
        evidence_parts.append(f"guide `{guide}`")
    return MriSignal(
        _CES_RUNTIME_DECLARATION_SIGNAL,
        "runtime",
        "CES runtime declaration with " + "; ".join(evidence_parts),
    )


def _runtime_declaration_from_pyproject(pyproject: dict[str, Any]) -> dict[str, Any]:
    tool = pyproject.get("tool", {}) if isinstance(pyproject.get("tool"), dict) else {}
    ces = tool.get("ces", {}) if isinstance(tool.get("ces"), dict) else {}
    declaration = ces.get("runtime_declaration", {}) if isinstance(ces.get("runtime_declaration"), dict) else {}
    return declaration if isinstance(declaration, dict) else {}


def _runtime_declaration_from_package_json(package_json: dict[str, Any]) -> dict[str, Any]:
    ces = package_json.get("ces", {}) if isinstance(package_json.get("ces"), dict) else {}
    declaration = ces.get("runtime_declaration", {}) if isinstance(ces.get("runtime_declaration"), dict) else {}
    return declaration if isinstance(declaration, dict) else {}


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
        if _looks_like_behavioral_test_file(path, relative):
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


def _looks_like_behavioral_test_file(path: Path, relative: str) -> bool:
    relative_path = Path(relative)
    parts = relative_path.parts
    if path.name in {"__init__.py", "conftest.py"}:
        return False
    if any(part in {"fixtures", "fixture", "support"} for part in parts):
        return False
    if "tests" in parts:
        return path.name.startswith("test_") or path.name.endswith("_test.py")
    return len(parts) == 1 and (path.name.startswith("test_") or path.name.endswith("_test.py"))


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
    if _RUNTIME_SIGNAL_NAMES & names:
        passed.append("runtime")
    if {".ces/verification-profile.json", _CES_COMPLETION_CONTRACT_SIGNAL, ".ces/config.yaml", ".ces/state.db"} & names:
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
    if not (_RUNTIME_SIGNAL_NAMES & names):
        missing.append("deployment/runtime declaration")
    if not ({".ces/verification-profile.json", _CES_COMPLETION_CONTRACT_SIGNAL} & names):
        missing.append("CES verification profile")
    return missing


def _classify_maturity(signals: list[MriSignal], findings: list[MriFinding], missing: list[str]) -> str:
    names = {signal.name for signal in signals}
    has_tests = bool({"pytest", "npm-test", "tests-directory"} & names)
    has_quality = bool({"ruff", "mypy", "eslint", "typescript"} & names)
    has_ci = "github-actions" in names
    has_runtime = bool(_RUNTIME_SIGNAL_NAMES & names)
    has_ces_state = bool(
        {".ces/verification-profile.json", _CES_COMPLETION_CONTRACT_SIGNAL, ".ces/config.yaml", ".ces/state.db"} & names
    )
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
        _CES_COMPLETION_CONTRACT_SIGNAL,
        _CES_RUNTIME_DECLARATION_SIGNAL,
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
    if not ({".ces/verification-profile.json", _CES_COMPLETION_CONTRACT_SIGNAL} & names):
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
    project_root: Path
    original_objective: str
    contract_status: str
    project_mode: str
    project_mode_reason: str
    detected_project_type: str
    detected_maturity: str
    intent_gate_decision: str
    intent_safe_next_step: str
    open_questions: tuple[str, ...]
    explicit_scope: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    must_not_break: tuple[str, ...]
    allowed_file_areas: tuple[str, ...]
    forbidden_changes: tuple[str, ...]
    slop_budget: tuple[str, ...]
    scope_drift_kill_switch: tuple[str, ...]
    slop_risks: tuple[dict[str, str], ...]
    thin_rescue_signals: dict[str, Any] | None
    prompt: str
    validation_commands: tuple[str, ...]
    non_goals: tuple[str, ...]
    completion_evidence_required: tuple[str, ...]
    ces_completion_expectations: tuple[str, ...]
    next_ces_command_after_implementation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "next_action": self.next_action.to_dict(),
            "project_root": str(self.project_root),
            "original_objective": self.original_objective,
            "contract_status": self.contract_status,
            "project_mode": self.project_mode,
            "project_mode_reason": self.project_mode_reason,
            "detected_project_type": self.detected_project_type,
            "detected_maturity": self.detected_maturity,
            "intent_gate": {
                "decision": self.intent_gate_decision,
                "safe_next_step": self.intent_safe_next_step,
                "open_questions": list(self.open_questions),
            },
            "scope": list(self.explicit_scope),
            "acceptance_criteria": list(self.acceptance_criteria),
            "must_not_break": list(self.must_not_break),
            "allowed_file_areas": list(self.allowed_file_areas),
            "forbidden_changes": list(self.forbidden_changes),
            "slop_budget": list(self.slop_budget),
            "scope_drift_kill_switch": list(self.scope_drift_kill_switch),
            "slop_risks": list(self.slop_risks),
            "thin_rescue_signals": self.thin_rescue_signals,
            "prompt": self.prompt,
            "validation_commands": list(self.validation_commands),
            "non_goals": list(self.non_goals),
            "completion_evidence_required": list(self.completion_evidence_required),
            "ces_completion_expectations": list(self.ces_completion_expectations),
            "next_ces_command_after_implementation": self.next_ces_command_after_implementation,
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


def build_next_prompt(
    project_root: str | Path,
    objective: str | None = None,
    *,
    acceptance_criteria: tuple[str, ...] | list[str] = (),
    must_not_break: tuple[str, ...] | list[str] = (),
) -> NextPromptReport:
    report = scan_project_mri(project_root)
    action = build_next_action(project_root)
    validation = _validation_commands_for(report)
    normalized_acceptance = tuple(item.strip() for item in acceptance_criteria if item.strip())
    normalized_must_not_break = tuple(item.strip() for item in must_not_break if item.strip())
    mode, mode_reason, thin_rescue = _project_mode_assessment(report)
    original_objective = _contract_objective(objective, action, thin_rescue)
    intent_preflight = classify_intent(
        original_objective,
        constraints=(),
        acceptance_criteria=normalized_acceptance,
        must_not_break=normalized_must_not_break,
        project_mode=mode,
        non_interactive=True,
    )
    contract_status = "blocked" if intent_preflight.decision == "blocked" else "implementation-ready"
    non_goals = _contract_non_goals(mode)
    explicit_scope = _contract_scope(
        report=report,
        action=action,
        mode=mode,
        objective=original_objective,
        contract_status=contract_status,
        thin_rescue=thin_rescue,
    )
    must_not_break_items = _contract_must_not_break(
        project_root=report.project_root,
        report=report,
        mode=mode,
        explicit_items=normalized_must_not_break,
    )
    allowed_file_areas = _allowed_file_areas(report, mode, thin_rescue, original_objective)
    forbidden_changes = _forbidden_changes(mode, thin_rescue)
    slop_budget = _slop_budget()
    scope_drift_kill_switch = _scope_drift_kill_switch()
    derived_acceptance = _contract_acceptance_criteria(
        report=report,
        action=action,
        mode=mode,
        objective=original_objective,
        explicit_items=normalized_acceptance,
        thin_rescue=thin_rescue,
        contract_status=contract_status,
    )
    slop_risks = tuple(finding.to_dict() for finding in report.risk_findings if finding.category == "ai-slop")
    completion_evidence_required = _completion_evidence_required()
    ces_completion_expectations = _ces_completion_expectations()
    next_ces_command = (
        "Clarify the request and rerun ces next-prompt." if contract_status == "blocked" else "ces verify"
    )
    prompt = _render_developer_intent_contract(
        report=report,
        original_objective=original_objective,
        contract_status=contract_status,
        project_mode=mode,
        project_mode_reason=mode_reason,
        intent_preflight=intent_preflight,
        explicit_scope=explicit_scope,
        non_goals=non_goals,
        must_not_break=must_not_break_items,
        acceptance_criteria=derived_acceptance,
        allowed_file_areas=allowed_file_areas,
        forbidden_changes=forbidden_changes,
        slop_budget=slop_budget,
        scope_drift_kill_switch=scope_drift_kill_switch,
        slop_risks=slop_risks,
        validation_commands=validation,
        completion_evidence_required=completion_evidence_required,
        ces_completion_expectations=ces_completion_expectations,
        next_ces_command=next_ces_command,
        thin_rescue=thin_rescue,
    )
    return NextPromptReport(
        next_action=action,
        project_root=report.project_root,
        original_objective=original_objective,
        contract_status=contract_status,
        project_mode=mode,
        project_mode_reason=mode_reason,
        detected_project_type=report.project_type,
        detected_maturity=report.maturity,
        intent_gate_decision=intent_preflight.decision,
        intent_safe_next_step=intent_preflight.safe_next_step,
        open_questions=tuple(question.question for question in intent_preflight.ledger.open_questions),
        explicit_scope=explicit_scope,
        acceptance_criteria=derived_acceptance,
        must_not_break=must_not_break_items,
        allowed_file_areas=allowed_file_areas,
        forbidden_changes=forbidden_changes,
        slop_budget=slop_budget,
        scope_drift_kill_switch=scope_drift_kill_switch,
        slop_risks=slop_risks,
        thin_rescue_signals=thin_rescue,
        prompt=prompt,
        validation_commands=validation,
        non_goals=non_goals,
        completion_evidence_required=completion_evidence_required,
        ces_completion_expectations=ces_completion_expectations,
        next_ces_command_after_implementation=next_ces_command,
    )


def build_production_passport(project_root: str | Path) -> ProductionPassportReport:
    report = scan_project_mri(project_root)
    sources = ["deterministic project scan"]
    if any(signal.name.startswith(".ces/") for signal in report.signals):
        sources.append("local CES evidence/state signals")
    return ProductionPassportReport(report, tuple(sources))


def build_ship_plan(project_root: str | Path, objective: str | None = None) -> ShipPlanReport:
    """Build a read-only beginner plan for getting from idea to proof-backed delivery."""

    action = build_next_action(project_root)
    prompt = build_next_prompt(project_root, objective)
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
    commands.extend(["ces verify", "ces proof", "ces passport", "ces launch rehearsal"])
    safety_notes = (
        "`ces ship` is read-only; it plans the path and explains the next command before any runtime launch.",
        'Use `ces build --from-scratch` only for empty/new projects; use plain `ces build "Add ..."` for brownfield changes.',
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
        package_json = _read_json(root / "package.json")
        package_manager = _node_package_manager(root, package_json)
        commands.append(
            RehearsalCommand(
                _node_run_command(package_manager, "test"),
                "recommended",
                "Run configured Node test command if dependencies are installed",
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
    quoted_request = shlex.quote(request)
    if request.startswith("-"):
        return f"ces build --from-scratch={quoted_request}"
    return f"ces build --from-scratch {quoted_request}"


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
        package_json = _read_json(report.project_root / "package.json")
        package_manager = _node_package_manager(report.project_root, package_json)
        commands.append(_node_run_command(package_manager, "test"))
    return tuple(commands)


def _bullet(items: Any) -> list[str]:
    values = list(items)
    if not values:
        return ["- None detected."]
    return [f"- {item}" for item in values]


def _project_mode_assessment(report: ProjectMriReport) -> tuple[str, str, dict[str, Any] | None]:
    if _is_greenfield_report(report):
        return (
            "greenfield",
            "No existing project spine was detected, so the contract should define the smallest runnable starting point.",
            None,
        )
    thin_rescue = _thin_rescue_signals(report)
    if thin_rescue is not None:
        return (
            "thin/born-thin rescue",
            "Existing project signals are fragile enough that CES should protect current behavior and force one rescue step before broader work.",
            thin_rescue,
        )
    return (
        "brownfield",
        "The repository has an existing project spine, so the contract should scope work to one bounded change while preserving current behavior.",
        None,
    )


def _thin_rescue_signals(report: ProjectMriReport) -> dict[str, Any] | None:
    names = {signal.name for signal in report.signals}
    missing_readme = "README.md" not in names
    missing_run_instructions = missing_readme or not _readme_has_instruction(report.project_root, ("run", "start"))
    missing_tests = not bool({"pytest", "npm-test", "tests-directory"} & names)
    missing_quality_gates = not bool({"ruff", "mypy", "eslint", "typescript"} & names)
    missing_ci = "github-actions" not in names
    missing_runtime_declaration = not bool(_RUNTIME_SIGNAL_NAMES & names)
    missing_verification_profile = ".ces/verification-profile.json" not in names
    slop_risks = tuple(finding.to_dict() for finding in report.risk_findings if finding.category == "ai-slop")
    spine_gap_count = sum(
        (
            missing_readme,
            missing_run_instructions,
            missing_tests,
            missing_quality_gates,
            missing_ci,
            missing_runtime_declaration,
            missing_verification_profile,
        )
    )
    weak_project_spine = spine_gap_count >= 3
    if report.maturity not in {"vibe-prototype", "local-app"} and not (weak_project_spine and slop_risks):
        return None
    if not weak_project_spine and not slop_risks:
        return None
    safest_next_step = _thin_rescue_next_step(
        missing_readme=missing_readme,
        missing_run_instructions=missing_run_instructions,
        missing_tests=missing_tests,
        missing_quality_gates=missing_quality_gates,
        missing_ci=missing_ci,
        missing_runtime_declaration=missing_runtime_declaration,
        missing_verification_profile=missing_verification_profile,
        slop_risks=slop_risks,
    )
    return {
        "missing_readme": missing_readme,
        "missing_run_instructions": missing_run_instructions,
        "missing_tests": missing_tests,
        "missing_quality_gates": missing_quality_gates,
        "missing_ci": missing_ci,
        "missing_runtime_declaration": missing_runtime_declaration,
        "missing_verification_profile": missing_verification_profile,
        "weak_project_spine": weak_project_spine,
        "slop_risks": list(slop_risks),
        "safest_next_step": safest_next_step,
    }


def _thin_rescue_next_step(
    *,
    missing_readme: bool,
    missing_run_instructions: bool,
    missing_tests: bool,
    missing_quality_gates: bool,
    missing_ci: bool,
    missing_runtime_declaration: bool,
    missing_verification_profile: bool,
    slop_risks: tuple[dict[str, str], ...],
) -> str:
    if missing_readme or missing_run_instructions:
        return "Document the current run and test path in README without changing user-visible behavior."
    if missing_tests:
        return "Add one focused characterization test for the primary current flow before adding new behavior."
    if slop_risks:
        risk = slop_risks[0]
        return (
            f"Fix the highest-severity AI-slop risk in {risk['evidence']} with the smallest behavior-preserving change."
        )
    if missing_verification_profile:
        return "Persist a CES verification profile that matches the checks the repository already uses."
    if missing_quality_gates or missing_ci:
        return "Add the smallest local verification/CI gate that matches the existing stack without introducing new frameworks."
    if missing_runtime_declaration:
        return "Declare the current runtime entrypoint or deployment command without changing deployment architecture."
    return "Make one minimal readiness improvement without broad rewrites or speculative cleanup."


def _contract_objective(
    objective: str | None,
    action: NextActionReport,
    thin_rescue: dict[str, Any] | None,
) -> str:
    if objective and objective.strip():
        return objective.strip()
    if thin_rescue is not None:
        return thin_rescue["safest_next_step"]
    return (
        "Create a small runnable app with README, tests, and run instructions"
        if action.recommended_command.startswith("ces build --from-scratch")
        else "Close the next smallest readiness gap without broad rewrites."
    )


def _contract_non_goals(mode: str) -> tuple[str, ...]:
    items = [
        "Do not add hosted services, dashboards, deployment platforms, or network calls.",
        "Do not weaken CES governance, approval, evidence, redaction, runtime-boundary, or consent gates.",
        "Do not print or commit secret values.",
        "Do not broaden scope beyond the explicit objective and acceptance criteria.",
        "Do not replace the existing stack, framework, or architecture unless the request explicitly requires it.",
    ]
    if mode == "thin/born-thin rescue":
        items.append("Do not turn the rescue step into a multi-epic rewrite, backlog, or redesign.")
    return tuple(items)


def _contract_scope(
    *,
    report: ProjectMriReport,
    action: NextActionReport,
    mode: str,
    objective: str,
    contract_status: str,
    thin_rescue: dict[str, Any] | None,
) -> tuple[str, ...]:
    if contract_status == "blocked":
        return (
            "Do not start implementation yet.",
            "Clarify the missing acceptance criteria and failure boundaries before editing code.",
        )
    if mode == "greenfield":
        return (
            f"Build exactly this objective: {objective}",
            "Keep the project to the smallest runnable shape with source, tests, README, and only the minimal config required to run and verify it.",
            "Prefer boring defaults over framework sprawl.",
        )
    if mode == "thin/born-thin rescue" and thin_rescue is not None:
        return (
            f"Use the original objective only as context: {objective}",
            f"Execute one rescue step only: {thin_rescue['safest_next_step']}",
            "Protect current fragile behavior while making the smallest verifiable readiness improvement.",
        )
    return (
        f"Build exactly this objective: {objective}",
        f"Keep the change bounded to the next safest step toward `{action.target_maturity}`.",
        "Preserve existing behavior and project conventions outside the scoped change.",
    )


def _contract_must_not_break(
    *,
    project_root: Path,
    report: ProjectMriReport,
    mode: str,
    explicit_items: tuple[str, ...],
) -> tuple[str, ...]:
    invariants = tuple(item.text for item in mine_project_invariants(project_root).invariants)
    defaults = [
        "Current working behavior outside the scoped change must keep working.",
        "Existing verification commands must keep passing once the scoped change is complete.",
    ]
    if mode != "greenfield":
        defaults.append(
            "Existing entrypoints, data files, and runtime boundaries must stay intact unless the scope explicitly says otherwise."
        )
    items = tuple(dict.fromkeys((*explicit_items, *invariants, *defaults)))
    return items or ("Keep the current project runnable and reviewable.",)


def _allowed_file_areas(
    report: ProjectMriReport,
    mode: str,
    thin_rescue: dict[str, Any] | None,
    objective: str,
) -> tuple[str, ...]:
    areas: list[str] = ["README.md", "tests/", "project config (pyproject.toml/package.json)"]
    if mode == "greenfield":
        areas.extend(["primary app source files", "minimal CI/quality config only if required for verification"])
    else:
        areas.extend(_objective_file_areas(report.project_root, objective))
        areas.extend(_paths_from_risk_findings(report.risk_findings))
        areas.append("docs/ and runtime entrypoint files only if the scoped step requires them")
    if thin_rescue is not None:
        if thin_rescue["missing_verification_profile"]:
            areas.append(".ces/verification-profile.json")
        if thin_rescue["missing_ci"]:
            areas.append(".github/workflows/")
    return tuple(dict.fromkeys(areas))


def _paths_from_risk_findings(findings: tuple[MriFinding, ...]) -> list[str]:
    areas: list[str] = []
    for finding in findings:
        if finding.category not in {"ai-slop", "secret-hygiene"}:
            continue
        for token in (part.strip() for part in finding.evidence.split(";")):
            candidate = token.split(" (", 1)[0].strip()
            if not candidate or "TODO/FIXME" in candidate:
                continue
            if "/" in candidate or candidate.endswith((".py", ".md", ".toml", ".json", ".yml", ".yaml")):
                areas.append(candidate)
    return areas


def _objective_file_areas(project_root: Path, objective: str) -> list[str]:
    objective_tokens = _objective_tokens(objective)
    if not objective_tokens:
        return []

    areas: list[str] = []
    if objective_tokens & _TEST_OBJECTIVE_TOKENS and _is_regular_dir(project_root / "tests"):
        areas.append("tests/")
    if objective_tokens & _RUNTIME_OBJECTIVE_TOKENS:
        if _is_regular_file(project_root / "pyproject.toml"):
            areas.append("pyproject.toml")
        if _is_regular_file(project_root / "docs" / "Production_Deployment_Guide.md"):
            areas.append("docs/Production_Deployment_Guide.md")
        if _is_regular_file(project_root / "Procfile"):
            areas.append("Procfile")

    scored_candidates: list[tuple[int, str]] = []
    for area in _objective_area_candidates(project_root):
        area_tokens = _area_tokens(area)
        overlap = objective_tokens & area_tokens
        if not overlap:
            continue
        high_signal_token_match = any(
            len(_normalize_objective_token(raw_token)) >= 6 and _normalize_objective_token(raw_token) in overlap
            for raw_token in re.findall(r"[a-z0-9]+", area.casefold())
        )
        if len(overlap) < 2 and not (high_signal_token_match and (area.startswith("src/") or "/" not in area)):
            continue
        score = len(overlap) * 10
        if area.startswith("src/"):
            score += 4
        elif area.startswith("tests/"):
            score += 2
        elif area.startswith("docs/"):
            score += 1
        if area.endswith("/"):
            score += 1
        if high_signal_token_match:
            score += 2
        scored_candidates.append((score, area))

    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    areas.extend(area for _, area in scored_candidates[:4])
    return list(dict.fromkeys(areas))


def _objective_area_candidates(project_root: Path) -> tuple[str, ...]:
    areas: set[str] = set()
    for path in _iter_project_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        if relative.startswith(_OBJECTIVE_HINT_EXCLUDED_PREFIXES):
            continue
        if relative in {"README.md", "pyproject.toml", "package.json", "Procfile"}:
            areas.add(relative)
            continue
        if relative.startswith(("src/", "tests/", "docs/", ".github/workflows/")):
            areas.add(relative)
        parts = Path(relative).parts
        if len(parts) >= 2 and parts[0] == "src":
            areas.add(f"{parts[0]}/{parts[1]}/")
    return tuple(sorted(areas))


def _objective_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in re.findall(r"[a-z0-9]+", text.casefold()):
        token = _normalize_objective_token(raw_token)
        if len(token) < 3 and token not in {"ci", "ui"}:
            continue
        if token in _OBJECTIVE_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _area_tokens(area: str) -> set[str]:
    return {_normalize_objective_token(token) for token in re.findall(r"[a-z0-9]+", area.casefold()) if token}


def _normalize_objective_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def _forbidden_changes(mode: str, thin_rescue: dict[str, Any] | None) -> tuple[str, ...]:
    items = [
        "Do not create or edit `.ces/state.db`, `.ces/artifacts/`, or `.ces/exports/`.",
        "Do not introduce a new framework, service, queue, database, or background job unless the request explicitly requires it.",
        "Do not rewrite unrelated modules, rename broad directories, or perform 'while I was here' refactors.",
        "Do not add dependencies without rationale plus lockfile and audit evidence.",
        "Do not change secret files or inline credentials.",
    ]
    if mode == "thin/born-thin rescue" and thin_rescue is not None:
        items.append("Do not mix multiple rescue steps into one implementation.")
    return tuple(items)


def _slop_budget() -> tuple[str, ...]:
    return (
        "No new framework unless the request cannot be satisfied with the current stack.",
        "No new service unless the request explicitly requires one.",
        "No broad rewrite unless the request explicitly asks for one.",
        "No dependency addition without rationale plus lockfile and audit evidence.",
        "No speculative features.",
        "No 'while I was here' refactors.",
    )


def _scope_drift_kill_switch() -> tuple[str, ...]:
    return (
        "If implementation requires changing scope, stop and report the needed decision.",
        "If acceptance criteria are insufficient for a high-risk change, block instead of guessing.",
        "If a simpler implementation satisfies the request, use it.",
    )


def _contract_acceptance_criteria(
    *,
    report: ProjectMriReport,
    action: NextActionReport,
    mode: str,
    objective: str,
    explicit_items: tuple[str, ...],
    thin_rescue: dict[str, Any] | None,
    contract_status: str,
) -> tuple[str, ...]:
    if contract_status == "blocked":
        return ("Do not implement until the missing acceptance criteria and failure boundaries are supplied.",)
    if explicit_items:
        return explicit_items
    if mode == "greenfield":
        return (
            f"The delivered project satisfies the stated objective exactly: {objective}",
            "The project is runnable with documented run instructions and includes focused automated verification.",
            "README documents how to run, test, and verify the project locally.",
            "Verification commands pass without broadening the stack beyond what the objective requires.",
        )
    if mode == "thin/born-thin rescue" and thin_rescue is not None:
        return (
            thin_rescue["safest_next_step"],
            "The current fragile behavior is preserved while the single rescue step is completed.",
            "The result closes one readiness gap with concrete local verification evidence and documents remaining gaps honestly.",
        )
    return (
        f"Only the requested change is delivered: {objective}",
        f"The next readiness target is advanced toward `{action.target_maturity}` without unrelated rewrites.",
        "Existing behavior and verification expectations remain intact outside the scoped change.",
        "Local verification commands pass and remaining blockers are called out explicitly.",
    )


def _completion_evidence_required() -> tuple[str, ...]:
    return (
        "List every file changed and explain why each file was in scope.",
        "Report the exact verification commands run and their exact results.",
        "Map each acceptance criterion to concrete proof.",
        "Disclose any open questions, deviations, or remaining blockers instead of hand-waving them.",
    )


def _ces_completion_expectations() -> tuple[str, ...]:
    return (
        "Emit exactly one `ces:completion` fenced block before exiting.",
        "Include `summary`, `files_changed`, `exploration_evidence`, `verification_commands`, and `criteria_satisfied`.",
        "If dependencies changed, include `dependency_changes` with rationale, lockfile evidence, and audit evidence.",
        "Include `complexity_notes`, `open_questions`, and `scope_deviations`; uncertainty must be disclosed, not hidden.",
        "Every acceptance criterion must appear once in `criteria_satisfied` with concrete evidence.",
    )


def _render_developer_intent_contract(
    *,
    report: ProjectMriReport,
    original_objective: str,
    contract_status: str,
    project_mode: str,
    project_mode_reason: str,
    intent_preflight: Any,
    explicit_scope: tuple[str, ...],
    non_goals: tuple[str, ...],
    must_not_break: tuple[str, ...],
    acceptance_criteria: tuple[str, ...],
    allowed_file_areas: tuple[str, ...],
    forbidden_changes: tuple[str, ...],
    slop_budget: tuple[str, ...],
    scope_drift_kill_switch: tuple[str, ...],
    slop_risks: tuple[dict[str, str], ...],
    validation_commands: tuple[str, ...],
    completion_evidence_required: tuple[str, ...],
    ces_completion_expectations: tuple[str, ...],
    next_ces_command: str,
    thin_rescue: dict[str, Any] | None,
) -> str:
    lines = [
        "# CES Developer Intent Contract",
        "",
        f"Original objective: {original_objective}",
        f"Contract status: **{contract_status}**",
        f"Project mode: **{project_mode}**",
        f"Detected project type: `{report.project_type}`",
        f"Detected maturity: **{report.maturity}**",
        f"Project root: `{report.project_root}`",
        "",
        "Build exactly what the user asked for. Treat overbuilding, scope drift, and speculative cleanup as failed checks.",
        "",
        "## Project mode rationale",
        "",
        project_mode_reason,
        "",
        "## Scope",
        "",
        *_bullet(explicit_scope),
        "",
        "## Non-goals",
        "",
        *_bullet(non_goals),
        "",
        "## Must-not-break behaviors",
        "",
        *_bullet(must_not_break),
        "",
        "## Acceptance criteria",
        "",
        *_bullet(acceptance_criteria),
        "",
        "## Allowed file areas",
        "",
        *_bullet(allowed_file_areas),
        "",
        "## Forbidden changes",
        "",
        *_bullet(forbidden_changes),
        "",
        "## Slop budget",
        "",
        *_bullet(slop_budget),
        "",
        "## Scope Drift Kill Switch",
        "",
        *_bullet(scope_drift_kill_switch),
    ]
    if thin_rescue is not None:
        lines.extend(
            [
                "",
                "## Thin/Born-Thin Rescue Signals",
                "",
                f"- Missing README: {thin_rescue['missing_readme']}",
                f"- Missing run instructions: {thin_rescue['missing_run_instructions']}",
                f"- Missing tests: {thin_rescue['missing_tests']}",
                f"- Missing CI/quality gates: {thin_rescue['missing_ci'] or thin_rescue['missing_quality_gates']}",
                f"- Missing runtime declaration: {thin_rescue['missing_runtime_declaration']}",
                f"- Missing verification profile: {thin_rescue['missing_verification_profile']}",
                f"- Weak project spine: {thin_rescue['weak_project_spine']}",
                f"- Single safest next step: {thin_rescue['safest_next_step']}",
            ]
        )
    lines.extend(["", "## AI-Slop Risks", ""])
    if slop_risks:
        lines.extend(
            _bullet(
                f"{finding['severity']} / {finding['title']} — {finding['evidence']}. {finding['recommendation']}"
                for finding in slop_risks
            )
        )
    else:
        lines.append("- No AI-slop risks were detected by the deterministic slop scan.")
    lines.extend(
        [
            "",
            "## Verification commands",
            "",
            *_bullet(validation_commands),
            "",
            "## Completion evidence required",
            "",
            *_bullet(completion_evidence_required),
            "",
            "## Exact `ces:completion` expectations",
            "",
            *_bullet(ces_completion_expectations),
            "",
            "## Intent Gate",
            "",
            f"- Decision: {intent_preflight.decision}",
            f"- Safe next step: {intent_preflight.safe_next_step}",
        ]
    )
    if intent_preflight.ledger.open_questions:
        lines.extend(
            [
                "- Open questions:",
                *[
                    f"  - {question.question} ({question.why_it_matters})"
                    for question in intent_preflight.ledger.open_questions
                ],
            ]
        )
    lines.extend(
        [
            "",
            "## Next CES command after implementation",
            "",
            f"`{next_ces_command}`",
            "",
            "## Reference completion schema",
            "",
            "````text",
            COMPLETION_CLAIM_INSTRUCTIONS.strip(),
            "````",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _readme_has_instruction(root: Path, verbs: tuple[str, ...]) -> bool:
    readme = root / "README.md"
    if not readme.is_file():
        return False
    text = readme.read_text(encoding="utf-8", errors="ignore")
    for verb in verbs:
        escaped = re.escape(verb)
        if re.search(rf"(?im)^\s*(?:[-*]\s*)?{escaped}\s*:\s*`?\S+", text):
            return True
        if re.search(rf"(?im)^\s*(?:```(?:bash|sh|shell)?\s*)?\$\s*\S*{escaped}\S*\b", text):
            return True
    return False
