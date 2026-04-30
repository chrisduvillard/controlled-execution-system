"""Tests for cli._builder_handoff.resolve_manifest_id branches.

Pins the two paths not exercised by the indirect CLI tests:
- An evidence_packet_id passed as provided_ref resolves to the context's manifest_id.
- A missing manifest with no context surfaces as typer.BadParameter.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer

from ces.cli._builder_handoff import resolve_manifest_id


def _make_local_store(*, snapshot: SimpleNamespace | None) -> MagicMock:
    store = MagicMock()
    store.get_latest_builder_session_snapshot = MagicMock(return_value=snapshot)
    return store


def test_resolve_manifest_id_swaps_evidence_ref_for_manifest_id() -> None:
    """When provided_ref matches the active evidence_packet_id, the resolver
    swaps it for the context's manifest_id (line 45)."""
    snapshot = SimpleNamespace(
        request="do something",
        manifest=SimpleNamespace(manifest_id="M-ABC"),
        evidence={"packet_id": "EP-XYZ"},
        project_mode="builder",
    )
    store = _make_local_store(snapshot=snapshot)

    manifest_id, context = resolve_manifest_id(
        provided_ref="EP-XYZ",
        local_store=store,
        missing_message="missing manifest",
    )

    assert manifest_id == "M-ABC"
    assert context is not None
    assert context.evidence_packet_id == "EP-XYZ"


def test_resolve_manifest_id_raises_when_no_ref_and_no_context() -> None:
    """No provided_ref, no builder snapshot -> typer.BadParameter (line 49)."""
    store = _make_local_store(snapshot=None)

    with pytest.raises(typer.BadParameter, match="give me a manifest"):
        resolve_manifest_id(
            provided_ref=None,
            local_store=store,
            missing_message="give me a manifest",
        )
