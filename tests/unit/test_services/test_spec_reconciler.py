from pathlib import Path

import pytest

from ces.control.spec.parser import SpecParser
from ces.control.spec.reconciler import ReconcileReport, SpecReconciler
from ces.control.spec.template_loader import TemplateLoader

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "specs"


@pytest.fixture
def loader(tmp_path: Path) -> TemplateLoader:
    return TemplateLoader(project_root=tmp_path)


def _load_spec(path: str, loader: TemplateLoader):
    return SpecParser(loader).parse((FIXTURES / path).read_text(encoding="utf-8"))


def test_reconcile_added_story(loader):
    # Start from minimal-valid (one story ST-01HXY); extend with a new story.
    base = (FIXTURES / "minimal-valid.md").read_text(encoding="utf-8")
    extended_text = base.replace(
        "## Rollback Plan",
        "### Story: New story\n"
        "- **id:** ST-NEW\n"
        "- **size:** XS\n"
        "- **description:** n\n"
        "- **acceptance:**\n"
        "  - n\n\n"
        "## Rollback Plan",
    )
    extended = SpecParser(loader).parse(extended_text)

    # Pretend only ST-01HXY has a manifest today.
    existing_manifest_story_ids = frozenset({"ST-01HXY"})
    reconciler = SpecReconciler(loader)
    report = reconciler.reconcile(extended, existing_manifest_story_ids)
    assert isinstance(report, ReconcileReport)
    assert report.added == ("ST-NEW",)
    assert report.orphaned == ()
    assert report.unchanged == ("ST-01HXY",)


def test_reconcile_orphaned_story(loader):
    # Spec has only ST-01HXY, but manifests for ST-01HXY and ST-DELETED exist.
    doc = _load_spec("minimal-valid.md", loader)
    existing = frozenset({"ST-01HXY", "ST-DELETED"})
    reconciler = SpecReconciler(loader)
    report = reconciler.reconcile(doc, existing)
    assert report.orphaned == ("ST-DELETED",)
    assert report.added == ()
    assert report.unchanged == ("ST-01HXY",)


def test_reconcile_all_buckets_empty_when_spec_and_manifests_match(loader):
    """Edge case: an all-unchanged report."""
    doc = _load_spec("minimal-valid.md", loader)
    existing = frozenset({"ST-01HXY"})
    report = SpecReconciler(loader).reconcile(doc, existing)
    assert report.added == ()
    assert report.orphaned == ()
    assert report.unchanged == ("ST-01HXY",)
