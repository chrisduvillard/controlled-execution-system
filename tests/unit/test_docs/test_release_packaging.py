"""Release packaging verification for public distribution."""

from __future__ import annotations

import os
import shutil
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from subprocess import run

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _uv_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["UV_CACHE_DIR"] = str(tmp_path / ".uv-cache")
    return env


def _require_local_build_backend() -> None:
    pytest.importorskip("hatchling")


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not str(destination).startswith(str(target_dir.resolve())):
                msg = f"Unsafe zip member path: {member.filename}"
                raise ValueError(msg)
            archive.extract(member, target_dir)


def test_project_metadata_declares_public_readme_and_license() -> None:
    """PyPI metadata should expose a README and bundled license."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["readme"] == "README.md"
    assert project["license"] == "MIT"
    assert project["urls"]["Repository"] == "https://github.com/chrisduvillard/controlled-execution-system"
    assert (ROOT / "LICENSE").is_file()


def test_sdist_excludes_internal_workspace_artifacts(tmp_path: Path) -> None:
    """The source distribution must not leak local planning or cache state."""
    _require_local_build_backend()
    dist_dir = tmp_path / "dist"
    uv_path = shutil.which("uv")
    assert uv_path is not None
    result = run(  # noqa: S603
        [uv_path, "build", "--sdist", "--out-dir", str(dist_dir), "--no-build-isolation"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=_uv_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr or result.stdout

    sdist_path = next(dist_dir.glob("controlled_execution_system-*.tar.gz"))
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = archive.getnames()

        blocked_fragments = (
            "/.planning/",
            "/.tmp/",
            "/.uv-cache/",
            "/.pytest_cache/",
            "/.ruff_cache/",
            "/.mypy_cache/",
            "/.venv/",
            "/.coverage",
            "/.ces/",
            "/dogfood-output/",
            "/voice-to-text-mvp/",
            "/runtime-transcripts/",
            "/state.db",
            "/keys/",
            "/.git/",
            "/.hypothesis/",
            "/__pycache__/",
            ".pyc",
            "env.sh",
        )
        leaked = [
            name for name in names if name.endswith("/.git") or any(fragment in name for fragment in blocked_fragments)
        ]
        assert leaked == []

        local_path_markers = ("/home/", "/Users/")
        text_members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.size <= 1_000_000 and not member.name.endswith((".png", ".gif", ".mp4"))
        ]
        leaked_local_paths: list[str] = []
        for member in text_members:
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            text = extracted.read().decode("utf-8", errors="ignore")
            if any(marker in text for marker in local_path_markers):
                leaked_local_paths.append(member.name)
        assert leaked_local_paths == []


def test_built_wheel_exposes_working_plain_cli(tmp_path: Path) -> None:
    """A plain wheel install must expose core CLI help surfaces."""
    _require_local_build_backend()
    dist_dir = tmp_path / "dist"
    uv_path = shutil.which("uv")
    assert uv_path is not None

    build = run(  # noqa: S603
        [uv_path, "build", "--wheel", "--out-dir", str(dist_dir), "--no-build-isolation"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=_uv_env(tmp_path),
    )
    assert build.returncode == 0, build.stderr or build.stdout

    wheel_path = next(dist_dir.glob("controlled_execution_system-*.whl"))
    install_target = tmp_path / "wheel-smoke-target"
    smoke_env = os.environ.copy()
    smoke_env["PYTHONPATH"] = str(install_target)
    # Force plain help output so Rich panel formatting doesn't fragment the
    # substrings we're asserting against (CI runners have narrow Rich default
    # widths that wrap ``Usage:`` and ``--template`` across multiple lines).
    smoke_env["NO_COLOR"] = "1"
    smoke_env["TERM"] = "dumb"
    smoke_env["COLUMNS"] = "200"

    _safe_extract_zip(wheel_path, install_target)
    smoke_cmd = "import sys; sys.argv[0] = 'ces'; from ces.cli import app; app()"

    root_help = run(  # noqa: S603
        [sys.executable, "-c", smoke_cmd, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=smoke_env,
    )
    assert root_help.returncode == 0, root_help.stderr or root_help.stdout
    assert "Production Autopilot for local AI-built projects." in root_help.stdout
    assert "ces ship" in root_help.stdout

    init_help = run(  # noqa: S603
        [sys.executable, "-c", smoke_cmd, "init", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=smoke_env,
    )
    assert init_help.returncode == 0, init_help.stderr or init_help.stdout
    assert "Usage: ces init" in init_help.stdout
    assert "Project name" in init_help.stdout
