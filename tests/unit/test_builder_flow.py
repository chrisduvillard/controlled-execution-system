"""Tests for builder-flow orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ces.cli._builder_flow import BuilderBriefDraft, BuilderFlowOrchestrator
from ces.shared.enums import LegacyDisposition


class TestBrownfieldCandidateDiscovery:
    def test_repo_signals_inform_brownfield_candidates(self, tmp_path: Path) -> None:
        (tmp_path / "billing_export.py").write_text("def export_rows():\n    return []\n")
        (tmp_path / "README.md").write_text("Billing exports and CSV flows.\n")
        orchestrator = BuilderFlowOrchestrator(tmp_path)

        brief = BuilderBriefDraft(
            request="Add invoice notes to exports",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=["CSV export format"],
            open_questions={},
            source_of_truth="README and exported CSV samples",
            critical_flows=["Billing export", "Monthly reconciliation"],
        )

        candidates = orchestrator.discover_brownfield_candidates(brief)

        assert len(candidates) >= 3
        assert any("CSV export format" in candidate for candidate in candidates)
        assert any("Billing export" in candidate for candidate in candidates)
        assert any("billing_export.py" in candidate for candidate in candidates)

    def test_grouped_candidates_are_ordered_and_preserve_provenance(self, tmp_path: Path) -> None:
        (tmp_path / "billing_export.py").write_text("def export_rows():\n    return []\n")
        orchestrator = BuilderFlowOrchestrator(tmp_path)

        brief = BuilderBriefDraft(
            request="Add invoice notes to exports",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=["billing_export.py"],
            open_questions={},
            source_of_truth="billing_export.py",
            critical_flows=["billing_export.py"],
        )

        groups = orchestrator.build_brownfield_review_groups(brief)

        assert [group.key for group in groups] == [
            "must_not_break",
            "critical_flows",
            "repo_signals",
            "source_of_truth",
        ]
        first_item = groups[0].items[0]
        assert first_item.description == "Preserve existing behavior for billing_export.py"
        assert first_item.primary_group == "must_not_break"
        source_item = groups[-1].items[0]
        assert source_item.description == "Validate behavior against billing_export.py"


class TestBuilderPromptCopy:
    def test_collect_brief_uses_short_builder_first_prompts(self, tmp_path: Path) -> None:
        orchestrator = BuilderFlowOrchestrator(tmp_path)
        prompts_seen: list[str] = []
        responses = iter(
            [
                "Expose an HTTP endpoint",
                "Users can create and complete habits",
                "Existing CLI commands",
            ]
        )

        def prompt_fn(prompt: str, default: str = "") -> str:
            prompts_seen.append(prompt)
            return next(responses)

        orchestrator.collect_brief(description="Build a habit tracker", prompt_fn=prompt_fn)

        assert prompts_seen == [
            "Any stack or constraint I should respect?",
            "What should be true when this is done?",
            "What should definitely stay working?",
        ]


class TestUnattendedBrief:
    def test_collect_brief_accepts_empty_defaults_for_unattended_mode(self, tmp_path: Path) -> None:
        """When prompt_fn returns defaults (empty strings), collect_brief still works."""
        orchestrator = BuilderFlowOrchestrator(tmp_path)

        def auto_prompt_fn(prompt: str, default: str = "") -> str:
            return default

        brief = orchestrator.collect_brief(
            description="Add healthcheck endpoint",
            prompt_fn=auto_prompt_fn,
        )

        assert brief.request == "Add healthcheck endpoint"
        assert brief.constraints == []
        assert brief.acceptance_criteria == []
        assert brief.must_not_break == []


class TestBrownfieldBehaviorCapture:
    @pytest.mark.asyncio
    async def test_capture_supports_group_defaults_and_item_overrides(self, tmp_path: Path) -> None:
        (tmp_path / "billing_export.py").write_text("def export_rows():\n    return []\n")
        orchestrator = BuilderFlowOrchestrator(tmp_path)
        brief = BuilderBriefDraft(
            request="Add invoice notes to exports",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=["CSV export format"],
            open_questions={},
            source_of_truth="README and snapshots",
            critical_flows=["Billing export"],
        )

        prompts = iter(
            [
                "preserve",
                "",
                "preserve",
                "change",
                "under_investigation",
                "",
                "preserve",
                "",
            ]
        )

        def prompt_fn(*_args, **_kwargs) -> str:
            return next(prompts)

        review_calls: list[str] = []
        mock_legacy = SimpleNamespace(
            register_behavior=AsyncMock(
                side_effect=[
                    SimpleNamespace(entry_id="OLB-1"),
                    SimpleNamespace(entry_id="OLB-2"),
                    SimpleNamespace(entry_id="OLB-3"),
                    SimpleNamespace(entry_id="OLB-4"),
                ]
            ),
            review_behavior=AsyncMock(
                side_effect=lambda **kwargs: (
                    review_calls.append(kwargs["disposition"].value)
                    or SimpleNamespace(entry_id=kwargs["entry_id"], disposition=kwargs["disposition"].value)
                )
            ),
        )

        decisions = await orchestrator.capture_brownfield_behaviors(
            brief=brief,
            legacy_behavior_service=mock_legacy,
            prompt_fn=prompt_fn,
            source_manifest_id="M-123",
        )

        assert len(decisions) == 4
        assert review_calls == [
            LegacyDisposition.PRESERVE.value,
            LegacyDisposition.CHANGE.value,
            LegacyDisposition.UNDER_INVESTIGATION.value,
            LegacyDisposition.PRESERVE.value,
        ]

    @pytest.mark.asyncio
    async def test_capture_resumes_from_checkpoint_without_reasking_reviewed_items(self, tmp_path: Path) -> None:
        (tmp_path / "billing_export.py").write_text("def export_rows():\n    return []\n")
        orchestrator = BuilderFlowOrchestrator(tmp_path)
        brief = BuilderBriefDraft(
            request="Add invoice notes to exports",
            project_mode="brownfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=["CSV export format"],
            open_questions={},
            source_of_truth="README and snapshots",
            critical_flows=["Billing export"],
        )

        groups = orchestrator.build_brownfield_review_groups(brief)
        review_state = {
            "groups": [
                {
                    "key": group.key,
                    "label": group.label,
                    "items": [
                        {
                            "description": item.description,
                            "primary_group": item.primary_group,
                            "rationale": item.rationale,
                            "secondary_groups": list(item.secondary_groups),
                        }
                        for item in group.items
                    ],
                }
                for group in groups
            ],
            "group_index": 1,
            "item_index": 0,
            "reviewed_candidates": [
                {
                    "description": groups[0].items[0].description,
                    "disposition": LegacyDisposition.PRESERVE.value,
                }
            ],
            "group_defaults": {"must_not_break": LegacyDisposition.PRESERVE.value},
        }

        prompts = iter(
            [
                "preserve",
                "change",
                "under_investigation",
                "",
                "preserve",
                "",
            ]
        )

        def prompt_fn(*_args, **_kwargs) -> str:
            return next(prompts)

        checkpoint_states: list[dict[str, object] | None] = []
        mock_legacy = SimpleNamespace(
            register_behavior=AsyncMock(
                side_effect=[
                    SimpleNamespace(entry_id="OLB-2"),
                    SimpleNamespace(entry_id="OLB-3"),
                    SimpleNamespace(entry_id="OLB-4"),
                ]
            ),
            review_behavior=AsyncMock(
                side_effect=lambda **kwargs: SimpleNamespace(
                    entry_id=kwargs["entry_id"], disposition=kwargs["disposition"].value
                )
            ),
        )

        decisions = await orchestrator.capture_brownfield_behaviors(
            brief=brief,
            legacy_behavior_service=mock_legacy,
            prompt_fn=prompt_fn,
            source_manifest_id="M-123",
            review_state=review_state,
            checkpoint_fn=checkpoint_states.append,
        )

        assert len(decisions) == 3
        assert mock_legacy.register_behavior.await_count == 3
        first_description = mock_legacy.register_behavior.await_args_list[0].kwargs["behavior_description"]
        assert first_description == groups[1].items[0].description
        assert checkpoint_states[-1] is None
