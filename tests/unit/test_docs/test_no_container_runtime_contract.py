"""Regression contract: CES has no container runtime support surface."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_ROOT_FILES = (
    ".containerignore",
    ".dockerignore",
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "Dockerfile",
)
FORBIDDEN_PATH_PARTS = (
    "sandbox.py",
    "test_docker_sandbox.py",
)
FORBIDDEN_TOKENS = (
    "Docker",
    "docker",
    "testcontainers",
    "docker-compose",
    "docker_integration",
    "CES_RUN_DOCKER_TESTS",
    "PostgresContainer",
)
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".worktrees",
    "build",
    "dist",
    "htmlcov",
}
EXCLUDED_FILES = {
    Path(__file__).resolve(),
}
EXCLUDED_PREFIXES = (Path("docs/audits"), Path("docs/historical"))
TEXT_SUFFIXES = {
    ".ini",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _is_excluded(path: Path) -> bool:
    if path.resolve() in EXCLUDED_FILES:
        return True
    rel = path.relative_to(ROOT)
    return any(part in EXCLUDED_DIRS for part in rel.parts) or any(
        rel == prefix or rel.is_relative_to(prefix) for prefix in EXCLUDED_PREFIXES
    )


def test_active_repository_has_no_container_runtime_surface() -> None:
    forbidden_paths = [name for name in FORBIDDEN_ROOT_FILES if (ROOT / name).exists()]
    forbidden_paths.extend(
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file() and not _is_excluded(path) and any(part in path.name for part in FORBIDDEN_PATH_PARTS)
    )

    token_hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or _is_excluded(path):
            continue
        rel = path.relative_to(ROOT)
        if path.name != "uv.lock" and path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                token_hits.append(f"{rel}: {token}")
                break

    assert not forbidden_paths, "container runtime files remain: " + ", ".join(sorted(forbidden_paths))
    assert not token_hits, "container runtime references remain: " + ", ".join(sorted(token_hits))
