"""Tests for ``SpecDecomposer`` — deterministic spec -> manifest expansion."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from ces.control.spec.decomposer import DecomposeResult, SpecDecomposer
from ces.control.spec.parser import SpecParser
from ces.control.spec.template_loader import TemplateLoader

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture()
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


@pytest.fixture()
def decomposer(loader: TemplateLoader) -> SpecDecomposer:
    return SpecDecomposer(loader)


def _load_spec(path: str, loader: TemplateLoader):
    parser = SpecParser(loader)
    return parser.parse((FIXTURES / path).read_text(encoding="utf-8"))


def test_decompose_produces_one_manifest_per_story(decomposer: SpecDecomposer, loader: TemplateLoader) -> None:
    doc = _load_spec("minimal-valid.md", loader)
    result = decomposer.decompose(doc)
    assert isinstance(result, DecomposeResult)
    assert len(result.manifests) == 1
    mf = result.manifests[0]
    assert mf.parent_spec_id == "SP-01HXY"
    assert mf.parent_story_id == "ST-01HXY"
    assert mf.acceptance_criteria == (
        "Returns 200 with JSON body",
        "p95 under 50ms",
    )


def test_decompose_resolves_dependencies_by_story_id(decomposer: SpecDecomposer, loader: TemplateLoader) -> None:
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    # Add a second story that depends on the first.
    extra = base.replace(
        "## Rollback Plan",
        "### Story: Add probe\n"
        "- **id:** ST-PROBE\n"
        "- **size:** XS\n"
        "- **depends_on:** [ST-01HXY]\n"
        "- **description:** docker compose probe.\n"
        "- **acceptance:**\n"
        "  - probe returns healthy\n\n"
        "## Rollback Plan",
    )
    doc = SpecParser(loader).parse(extra)
    result = decomposer.decompose(doc)
    assert len(result.manifests) == 2
    probe = next(m for m in result.manifests if m.parent_story_id == "ST-PROBE")
    first = next(m for m in result.manifests if m.parent_story_id == "ST-01HXY")
    # ManifestDependency's identifier field is `artifact_id` (NOT manifest_id).
    dep_ids = tuple(d.artifact_id for d in probe.dependencies)
    assert first.manifest_id in dep_ids


def test_decompose_uses_tiered_ttl_per_governance_policy(decomposer: SpecDecomposer, loader: TemplateLoader) -> None:
    doc = _load_spec("minimal-valid.md", loader)
    result = decomposer.decompose(doc)
    mf = result.manifests[0]
    # minimal-valid has blast_radius: isolated → RiskTier.C → 14d TTL.
    expected_window = mf.expires_at - mf.created_at
    assert expected_window == timedelta(days=14), f"Tier C manifest must have 14-day TTL (D-15), got {expected_window}"


def test_decompose_raises_when_oracle_returns_no_matched_rule(loader: TemplateLoader) -> None:
    """Defensive guard: an oracle result with matched_rule=None surfaces as RuntimeError."""
    from unittest.mock import MagicMock

    from ces.control.models.oracle_result import OracleClassificationResult

    mock_oracle = MagicMock()
    mock_oracle.classify_from_hints.return_value = OracleClassificationResult(
        matched_rule=None,
        confidence=0.0,
        top_matches=(),
        action="human_classify",
    )
    decomposer = SpecDecomposer(loader, oracle=mock_oracle)
    doc = _load_spec("minimal-valid.md", loader)

    with pytest.raises(RuntimeError, match="no matched rule"):
        decomposer.decompose(doc)
