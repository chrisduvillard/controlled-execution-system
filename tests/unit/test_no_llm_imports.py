"""Tests that LLM libraries are never imported in the control or shared planes.

LLM-05 mandates zero LLM imports (anthropic, openai, litellm, langchain)
in ces/control/ and ces/shared/. This prevents non-deterministic LLM calls
from contaminating the deterministic control plane.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Prohibited top-level modules that indicate LLM usage
PROHIBITED_MODULES = frozenset(
    {
        "anthropic",
        "openai",
        "litellm",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langchain_openai",
        "langchain_anthropic",
    }
)

# Directories that must be free of LLM imports
CONTROL_PLANE_DIRS = [
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "control",
    pathlib.Path(__file__).resolve().parents[2] / "src" / "ces" / "shared",
]


def _collect_python_files() -> list[pathlib.Path]:
    """Collect all .py files under control plane directories."""
    files: list[pathlib.Path] = []
    for directory in CONTROL_PLANE_DIRS:
        if directory.is_dir():
            files.extend(directory.rglob("*.py"))
    return sorted(files)


def _extract_imports(filepath: pathlib.Path) -> list[tuple[str, int]]:
    """Parse a Python file and extract all imported module names with line numbers.

    Returns a list of (module_root, line_number) tuples.
    """
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                imports.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                root = node.module.split(".")[0]
                imports.append((root, node.lineno))
    return imports


class TestNoLLMImportsInControlPlane:
    """LLM-05: The control plane and shared plane must not import LLM libraries."""

    def test_control_plane_dirs_exist(self) -> None:
        """Sanity check: control plane directories must exist."""
        for directory in CONTROL_PLANE_DIRS:
            assert directory.is_dir(), f"Expected directory not found: {directory}"

    def test_python_files_found(self) -> None:
        """Sanity check: there should be Python files to scan."""
        files = _collect_python_files()
        assert len(files) > 0, "No Python files found in control plane directories"

    def test_no_llm_imports_in_any_control_plane_file(self) -> None:
        """Every .py file in ces/control/ and ces/shared/ must be free of LLM imports."""
        violations: list[str] = []
        for filepath in _collect_python_files():
            for module_root, lineno in _extract_imports(filepath):
                if module_root in PROHIBITED_MODULES:
                    relative = filepath.relative_to(pathlib.Path(__file__).resolve().parents[2] / "src")
                    violations.append(f"  {relative}:{lineno} imports '{module_root}'")

        assert violations == [], (
            f"LLM-05 violation: found {len(violations)} prohibited LLM import(s) "
            f"in control/shared plane:\n" + "\n".join(violations)
        )

    @pytest.mark.parametrize(
        "prohibited_module",
        sorted(PROHIBITED_MODULES),
        ids=sorted(PROHIBITED_MODULES),
    )
    def test_specific_module_not_imported(self, prohibited_module: str) -> None:
        """Each prohibited module is individually verified absent."""
        violations: list[str] = []
        for filepath in _collect_python_files():
            for module_root, lineno in _extract_imports(filepath):
                if module_root == prohibited_module:
                    relative = filepath.relative_to(pathlib.Path(__file__).resolve().parents[2] / "src")
                    violations.append(f"  {relative}:{lineno}")

        assert violations == [], f"LLM-05 violation: '{prohibited_module}' imported in control plane:\n" + "\n".join(
            violations
        )
