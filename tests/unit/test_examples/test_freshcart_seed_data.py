"""Regression tests for the public FreshCart seed example."""

from __future__ import annotations

import json

from ces.shared.crypto import sha256_hash
from examples.freshcart.seed_data import (
    _build_artifacts,
    _truth_artifact_row_from_artifact,
)


def test_truth_artifact_row_from_artifact_matches_current_schema() -> None:
    """The demo seed helper must construct rows accepted by TruthArtifactRow."""
    artifact = _build_artifacts()[0]

    row = _truth_artifact_row_from_artifact(artifact)

    assert row.id == artifact["artifact_id"]
    assert row.type == artifact["type"]
    assert row.version == 1
    assert row.status == "approved"
    assert row.owner == "freshcart-demo"
    assert row.project_id == "freshcart"
    assert row.content == artifact["content"]
    assert row.content_hash == sha256_hash(json.dumps(artifact["content"], sort_keys=True))
