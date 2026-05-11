"""Stable JSON IO for harness change manifests."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ces.harness_evolution.models import HarnessChangeManifest
from ces.harness_evolution.paths import HarnessPaths, create_harness_layout


def _manifest_filename(change_id: str) -> str:
    filename = f"{change_id}.json"
    if Path(filename).name != filename or "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("change_id must produce a safe manifest filename")
    return filename


def manifest_to_stable_json(manifest: HarnessChangeManifest) -> str:
    """Serialize a manifest with deterministic key order and newline."""

    return json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def write_manifest(project_root: Path, manifest: HarnessChangeManifest) -> Path:
    """Write `manifest` beneath `.ces/harness/change_manifests/` only."""

    paths = create_harness_layout(project_root)
    path = paths.change_manifests / _manifest_filename(manifest.change_id)
    resolved_dir = paths.change_manifests.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_dir):
        raise ValueError("manifest path must stay under change_manifests")
    path.write_text(manifest_to_stable_json(manifest), encoding="utf-8")
    path.chmod(0o600)
    return path


def read_manifest(path: Path, *, project_root: Path | None = None) -> HarnessChangeManifest:
    """Read and validate a harness change manifest JSON file."""

    path = path.resolve()
    if project_root is not None:
        allowed_dir = HarnessPaths.for_project(project_root).change_manifests.resolve()
        if not path.is_relative_to(allowed_dir):
            raise ValueError("manifest path must be under .ces/harness/change_manifests")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return HarnessChangeManifest.model_validate(payload)
    except ValidationError:
        raise
    except json.JSONDecodeError as exc:
        msg = f"invalid manifest JSON: {path}"
        raise ValueError(msg) from exc
