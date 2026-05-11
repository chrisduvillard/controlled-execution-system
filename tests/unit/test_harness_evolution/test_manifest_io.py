"""Tests for harness change manifest JSON IO."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ces.harness_evolution.manifest_io import read_manifest, write_manifest
from ces.harness_evolution.models import HarnessChangeManifest, HarnessComponentType
from ces.harness_evolution.paths import HarnessPaths, create_harness_layout


def _manifest(change_id: str = "hchg-roundtrip") -> HarnessChangeManifest:
    return HarnessChangeManifest.model_validate(
        {
            "change_id": change_id,
            "title": "Change validation guidance",
            "component_type": HarnessComponentType.TOOL_POLICY,
            "files_changed": ["src/ces/harness/policy.md"],
            "evidence_refs": ["analysis:proxy-validation"],
            "failure_pattern": "Proxy validation was accepted.",
            "root_cause_hypothesis": "Policy was under-specified.",
            "predicted_fixes": ["Reject proxy-only checks."],
            "predicted_regressions": ["More blocked completions."],
            "validation_plan": ["Run focused dogfood transcript."],
            "rollback_condition": "Rollback if false blocks increase.",
        }
    )


def test_round_trip_manifest_preserves_fields(tmp_path: Path) -> None:
    create_harness_layout(tmp_path)
    manifest = _manifest()
    written = write_manifest(tmp_path, manifest)

    loaded = read_manifest(written)

    assert loaded == manifest
    assert written == HarnessPaths.for_project(tmp_path).change_manifests / "hchg-roundtrip.json"


def test_manifest_json_is_stably_sorted(tmp_path: Path) -> None:
    create_harness_layout(tmp_path)
    written = write_manifest(tmp_path, _manifest())

    first_line_after_brace = written.read_text(encoding="utf-8").splitlines()[1]
    assert first_line_after_brace.startswith('  "change_id"')
    parsed = json.loads(written.read_text(encoding="utf-8"))
    assert parsed["predicted_fixes"] == ["Reject proxy-only checks."]


def test_write_manifest_rejects_path_traversal_change_id(tmp_path: Path) -> None:
    create_harness_layout(tmp_path)

    unsafe = _manifest().model_copy(update={"change_id": "hchg-../evil"})
    with pytest.raises(ValueError, match="safe manifest filename"):
        write_manifest(tmp_path, unsafe)


def test_read_manifest_rejects_path_outside_change_manifests(tmp_path: Path) -> None:
    create_harness_layout(tmp_path)
    outside = tmp_path / ".ces" / "harness" / "evil.json"
    outside.write_text(_manifest().model_dump_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="change_manifests"):
        read_manifest(outside, project_root=tmp_path)
