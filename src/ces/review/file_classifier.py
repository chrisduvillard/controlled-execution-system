"""Deterministic file classification for semantic review artifacts."""

from __future__ import annotations

from pathlib import PurePosixPath

from ces.review.models import FileClassification

_DOC_EXTS = {".md", ".rst", ".txt", ".adoc"}
_TEST_MARKERS = ("tests/", "/tests/", "test_", "_test.", ".spec.", ".test.")
_LOCKFILES = {"uv.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Cargo.lock"}
_CONFIG_NAMES = {"pyproject.toml", "setup.cfg", "tox.ini", "mypy.ini", "ruff.toml", ".pre-commit-config.yaml"}
_GENERATED_MARKERS = ("generated", "dist/", "build/", "__snapshots__", ".min.js")
_LANG_BY_EXT = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".css": "css",
    ".rs": "rust",
    ".go": "go",
}


def classify_path(path: str) -> FileClassification:
    """Classify a repository path into a review role and conceptual area."""

    normalized = path.replace("\\", "/").lstrip("./")
    lowered = normalized.lower()
    pure = PurePosixPath(normalized)
    name = pure.name
    suffix = pure.suffix.lower()
    parts = pure.parts
    signals: list[str] = []
    role = "unknown"
    area = "unknown"

    if lowered in _LOCKFILES or name in _LOCKFILES:
        role = "lockfile"
        area = "packaging"
        signals.append("lockfile name")
    elif lowered.startswith(".github/workflows/"):
        role = "ci"
        area = "ci"
        signals.append("GitHub workflow path")
    elif name in _CONFIG_NAMES or lowered.startswith((".github/", ".gitlab/")):
        role = "config"
        area = "packaging" if name in {"pyproject.toml", "setup.cfg"} else "ci"
        signals.append("configuration filename")
    elif lowered.startswith("docs/") or suffix in _DOC_EXTS:
        role = "doc"
        area = "docs"
        signals.append("documentation path or extension")
    elif lowered.startswith("tests/") or any(marker in lowered for marker in _TEST_MARKERS):
        role = "test"
        area = "tests"
        signals.append("test path pattern")
    elif lowered.startswith("src/") or suffix in {".py", ".js", ".ts", ".tsx", ".go", ".rs"}:
        role = "source"
        area = _classify_source_area(parts, lowered)
        signals.append("source path or executable extension")
    elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ico"}:
        role = "asset"
        area = "assets"
        signals.append("binary/asset extension")

    generated = any(marker in lowered for marker in _GENERATED_MARKERS)
    if generated:
        signals.append("generated artifact marker")
        if role == "unknown":
            role = "generated"

    return FileClassification(
        role=role,
        conceptual_area=area,
        language=_LANG_BY_EXT.get(suffix, "unknown"),
        generated=generated,
        lockfile=role == "lockfile",
        signals=tuple(signals or ("no deterministic classifier matched",)),
    )


def _classify_source_area(parts: tuple[str, ...], lowered: str) -> str:
    joined = "/".join(parts)
    ces_area_map = {
        "src/ces/cli": "cli",
        "src/ces/execution": "execution",
        "src/ces/harness": "harness",
        "src/ces/harness_evolution": "harness",
        "src/ces/verification": "verification",
        "src/ces/intake": "intake",
        "src/ces/local_store": "persistence",
        "src/ces/control": "governance",
        "src/ces/review": "review",
        "src/ces/observability": "sensors",
        "src/ces/brownfield": "brownfield",
        "src/ces/emergency": "safety",
    }
    for prefix, area in ces_area_map.items():
        if joined.startswith(prefix):
            return area
    if "auth" in lowered or "secret" in lowered or "credential" in lowered:
        return "security"
    if "runtime" in lowered or "adapter" in lowered:
        return "runtime"
    return "source"
