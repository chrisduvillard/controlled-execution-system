"""Package artifact hygiene contracts."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BULKY_DOC_ASSET_SUFFIXES = (".gif", ".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp")
FORBIDDEN_ARTIFACT_PATH_PARTS = (
    "/.ces/",
    "/.github/",
    "/.hermes/",
    "/.pytest_cache/",
    "/.ruff_cache/",
    "/dogfood-output/",
    "/runtime-transcripts/",
    "/tests/",
)


def _build_artifacts(out_dir: Path) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None
    subprocess.run([uv, "build", "--out-dir", str(out_dir)], cwd=ROOT, check=True)  # noqa: S603
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return wheels[0], sdists[0]


def _sdist_names(path: Path) -> list[str]:
    with tarfile.open(path) as archive:
        return archive.getnames()


def _wheel_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def test_sdist_excludes_bulky_documentation_media(tmp_path: Path) -> None:
    """Source distributions should not ship heavy docs media assets."""
    _wheel, sdist = _build_artifacts(tmp_path)

    names = _sdist_names(sdist)

    bulky_docs_assets = [
        name for name in names if "/docs/assets/" in name and name.lower().endswith(BULKY_DOC_ASSET_SUFFIXES)
    ]
    assert bulky_docs_assets == []


def test_distribution_artifacts_exclude_private_and_test_state(tmp_path: Path) -> None:
    """Published artifacts should not contain CI-private, test, or local agent state."""
    wheel, sdist = _build_artifacts(tmp_path)

    inspected = _wheel_names(wheel) + _sdist_names(sdist)

    leaked = [name for name in inspected for forbidden in FORBIDDEN_ARTIFACT_PATH_PARTS if forbidden in f"/{name}"]
    assert leaked == []
