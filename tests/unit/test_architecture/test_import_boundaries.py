"""Architecture-boundary regression tests."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ces"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _imported_from_symbols(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.update((node.module, alias.name) for alias in node.names)
    return imports


def test_control_plane_does_not_import_harness_plane() -> None:
    offenders = []
    for path in (SRC / "control").rglob("*.py"):
        imports = _imported_modules(path)
        if any(module == "ces.harness" or module.startswith("ces.harness.") for module in imports):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_shared_secret_redaction_is_not_imported_from_execution_outside_execution_plane() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if SRC / "execution" in path.parents:
            continue
        imports = _imported_modules(path)
        imported_symbols = _imported_from_symbols(path)
        if "ces.execution.secrets" in imports or ("ces.execution", "secrets") in imported_symbols:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_control_plane_status_uses_canonical_control_model_imports() -> None:
    """New source code should not reintroduce harness-owned readiness models."""

    compatibility_module = SRC / "harness" / "models" / "control_plane_status.py"
    offenders = []
    for path in SRC.rglob("*.py"):
        if path == compatibility_module:
            continue
        imports = _imported_modules(path)
        imported_symbols = _imported_from_symbols(path)
        forbidden_symbol_imports = {
            ("ces.harness.models", "ControlPlaneStatus"),
            ("ces.harness.models", "GovernanceState"),
        }
        if "ces.harness.models.control_plane_status" in imports or imported_symbols & forbidden_symbol_imports:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
