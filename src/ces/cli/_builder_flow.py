"""Builder-first orchestration helpers for `ces build`."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ces.intent_gate.classifier import classify_intent
from ces.intent_gate.models import IntentGatePreflight
from ces.shared.enums import LegacyDisposition

PromptFn = Callable[..., str]

_DISPOSITION_VALUES = {item.value for item in LegacyDisposition}
_BROWNFIELD_GROUP_ORDER = (
    "must_not_break",
    "critical_flows",
    "repo_signals",
    "source_of_truth",
)
_BROWNFIELD_GROUP_LABELS = {
    "must_not_break": "Must Not Break",
    "critical_flows": "Critical Flows",
    "repo_signals": "Repo Signals",
    "source_of_truth": "Source Of Truth",
}


@dataclass(frozen=True)
class BrownfieldReviewCandidate:
    description: str
    primary_group: str
    rationale: str
    secondary_groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrownfieldReviewGroup:
    key: str
    label: str
    items: list[BrownfieldReviewCandidate]


@dataclass(frozen=True)
class BuilderBriefDraft:
    request: str
    project_mode: str
    constraints: list[str]
    acceptance_criteria: list[str]
    must_not_break: list[str]
    open_questions: dict[str, str]
    source_of_truth: str = ""
    critical_flows: list[str] | None = None
    intent_preflight: IntentGatePreflight | None = None


class BuilderFlowOrchestrator:
    """Collect builder intent and turn it into CES-ready local context."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def collect_brief(
        self,
        *,
        description: str | None,
        prompt_fn: PromptFn,
        force_greenfield: bool = False,
        force_brownfield: bool = False,
        provided_constraints: list[str] | None = None,
        provided_acceptance_criteria: list[str] | None = None,
        provided_must_not_break: list[str] | None = None,
        provided_source_of_truth: str | None = None,
        provided_critical_flows: list[str] | None = None,
        non_interactive: bool = False,
        intent_gate_enabled: bool = True,
    ) -> BuilderBriefDraft:
        request = description.strip() if description else ""
        if not request:
            request = prompt_fn("What do you want to build?").strip()

        project_mode = self.detect_project_mode(
            force_greenfield=force_greenfield,
            force_brownfield=force_brownfield,
        )

        if provided_constraints:
            constraints_raw = "\n".join(provided_constraints)
        else:
            constraints_raw = prompt_fn(
                "Any stack or constraint I should respect?",
                default="",
            ).strip()
        if provided_acceptance_criteria:
            acceptance_raw = "\n".join(provided_acceptance_criteria)
        else:
            acceptance_raw = prompt_fn(
                "What should be true when this is done?",
                default="",
            ).strip()
        if provided_must_not_break:
            must_not_break_raw = "\n".join(provided_must_not_break)
        else:
            must_not_break_raw = prompt_fn(
                "What should definitely stay working?",
                default="",
            ).strip()

        source_of_truth = ""
        critical_flows: list[str] = []
        open_questions = {
            "constraints": constraints_raw,
            "acceptance": acceptance_raw,
            "must_not_break": must_not_break_raw,
        }

        if project_mode == "brownfield":
            if provided_source_of_truth is not None:
                source_of_truth = provided_source_of_truth.strip()
            else:
                source_of_truth = prompt_fn(
                    "What best reflects today's behavior?",
                    default="",
                ).strip()
            if provided_critical_flows:
                critical_flows_raw = "\n".join(provided_critical_flows)
            else:
                critical_flows_raw = prompt_fn(
                    "Which workflows matter most to keep working?",
                    default="",
                ).strip()
            critical_flows = _split_flows(critical_flows_raw)
            open_questions["source_of_truth"] = source_of_truth
            open_questions["critical_flows"] = critical_flows_raw

        constraints = _split_list(constraints_raw)
        acceptance_criteria = _split_list(acceptance_raw)
        must_not_break = _split_list(must_not_break_raw)
        intent_preflight = None
        if intent_gate_enabled:
            intent_preflight = classify_intent(
                request,
                constraints,
                acceptance_criteria,
                must_not_break,
                project_mode,
                non_interactive,
            )

        if (
            intent_gate_enabled
            and intent_preflight is not None
            and not non_interactive
            and intent_preflight.decision == "ask"
        ):
            answers: list[str] = []
            for question in intent_preflight.ledger.open_questions:
                answer = prompt_fn(question.question, default="").strip()
                open_questions[question.question] = answer
                if answer:
                    answers.append(answer)
            if answers:
                acceptance_criteria.extend(answers)
                intent_preflight = classify_intent(
                    request,
                    constraints,
                    acceptance_criteria,
                    must_not_break,
                    project_mode,
                    non_interactive,
                )

        return BuilderBriefDraft(
            request=request,
            project_mode=project_mode,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            must_not_break=must_not_break,
            open_questions=open_questions,
            source_of_truth=source_of_truth,
            critical_flows=critical_flows,
            intent_preflight=intent_preflight,
        )

    def detect_project_mode(
        self,
        *,
        force_greenfield: bool = False,
        force_brownfield: bool = False,
    ) -> str:
        if force_greenfield:
            return "greenfield"
        if force_brownfield:
            return "brownfield"
        return "brownfield" if self._has_repo_files() else "greenfield"

    def propose_manifest(
        self,
        *,
        brief: BuilderBriefDraft,
        runtime_adapter: Any,
    ) -> dict[str, Any]:
        truth_artifacts = {
            "builder_brief": {
                "request": brief.request,
                "project_mode": brief.project_mode,
                "constraints": brief.constraints,
                "acceptance_criteria": brief.acceptance_criteria,
                "must_not_break": brief.must_not_break,
            }
        }
        return runtime_adapter.generate_manifest_assist(truth_artifacts, brief.request)

    async def capture_brownfield_behaviors(
        self,
        *,
        brief: BuilderBriefDraft,
        legacy_behavior_service: Any,
        prompt_fn: PromptFn,
        source_manifest_id: str | None = None,
        review_state: dict[str, Any] | None = None,
        checkpoint_fn: Callable[[dict[str, Any] | None], None] | None = None,
    ) -> list[Any]:
        if brief.project_mode != "brownfield" or legacy_behavior_service is None:
            return []

        state = self._normalize_review_state(brief, review_state)
        decisions: list[Any] = []
        reviewed_candidates = {item["description"]: item["disposition"] for item in state["reviewed_candidates"]}
        reviewed_entry_ids = list(state["reviewed_entry_ids"])
        group_defaults = {key: _normalize_disposition(value) for key, value in state["group_defaults"].items()}

        for group_index, group in enumerate(state["groups"]):
            if group_index < state["group_index"]:
                continue

            if group.key not in group_defaults:
                checkpoint = self._review_checkpoint(
                    state,
                    group_index=group_index,
                    item_index=0,
                    reviewed_candidates=reviewed_candidates,
                    reviewed_entry_ids=reviewed_entry_ids,
                    group_defaults=group_defaults,
                )
                if checkpoint_fn is not None:
                    checkpoint_fn(checkpoint)
                group_default = prompt_fn(
                    (f"{group.label}: default disposition for remaining items ({len(group.items)} total)"),
                    default=LegacyDisposition.PRESERVE.value,
                )
                group_defaults[group.key] = _normalize_disposition(group_default)

            start_item_index = state["item_index"] if group_index == state["group_index"] else 0
            for item_index, candidate in enumerate(group.items):
                if item_index < start_item_index:
                    continue
                if candidate.description in reviewed_candidates:
                    continue

                checkpoint = self._review_checkpoint(
                    state,
                    group_index=group_index,
                    item_index=item_index,
                    reviewed_candidates=reviewed_candidates,
                    reviewed_entry_ids=reviewed_entry_ids,
                    group_defaults=group_defaults,
                )
                if checkpoint_fn is not None:
                    checkpoint_fn(checkpoint)

                default_disposition = group_defaults[group.key]
                disposition = prompt_fn(
                    self._build_review_prompt(candidate, group=group),
                    default=default_disposition,
                )
                normalized_disposition = _normalize_disposition(disposition or default_disposition)
                reviewed_candidates[candidate.description] = normalized_disposition

                entry = await legacy_behavior_service.register_behavior(
                    system=self._project_root.name,
                    behavior_description=candidate.description,
                    inferred_by="builder-flow",
                    confidence=0.75,
                    source_manifest_id=source_manifest_id,
                )
                reviewed = await legacy_behavior_service.review_behavior(
                    entry_id=entry.entry_id,
                    disposition=LegacyDisposition(normalized_disposition),
                    reviewed_by="cli-user",
                )
                reviewed_entry_ids.append(entry.entry_id)
                decisions.append(reviewed)

                next_group_index, next_item_index = self._advance_review_position(
                    groups=state["groups"],
                    group_index=group_index,
                    item_index=item_index,
                )
                checkpoint = self._review_checkpoint(
                    state,
                    group_index=next_group_index,
                    item_index=next_item_index,
                    reviewed_candidates=reviewed_candidates,
                    reviewed_entry_ids=reviewed_entry_ids,
                    group_defaults=group_defaults,
                )
                if checkpoint_fn is not None:
                    checkpoint_fn(checkpoint)

        if checkpoint_fn is not None:
            checkpoint_fn(None)
        return decisions

    def build_brownfield_review_groups(self, brief: BuilderBriefDraft) -> list[BrownfieldReviewGroup]:
        grouped_candidates: dict[str, dict[str, Any]] = {}

        def add_candidate(
            *,
            description: str,
            group: str,
            rationale: str,
        ) -> None:
            existing = grouped_candidates.get(description)
            if existing is None:
                grouped_candidates[description] = {
                    "description": description,
                    "primary_group": group,
                    "rationale": rationale,
                    "secondary_groups": [],
                }
                return

            existing_rank = _BROWNFIELD_GROUP_ORDER.index(existing["primary_group"])
            new_rank = _BROWNFIELD_GROUP_ORDER.index(group)
            if new_rank < existing_rank:
                existing["secondary_groups"].append(existing["primary_group"])
                existing["primary_group"] = group
                existing["rationale"] = rationale
            elif group != existing["primary_group"] and group not in existing["secondary_groups"]:
                existing["secondary_groups"].append(group)

        for item in brief.must_not_break:
            add_candidate(
                description=f"Preserve existing behavior for {item}",
                group="must_not_break",
                rationale="Surfaced from the operator's must-not-break constraints.",
            )
        for flow in brief.critical_flows or []:
            add_candidate(
                description=f"Critical flow remains intact: {flow}",
                group="critical_flows",
                rationale="Surfaced from the operator's critical brownfield flows.",
            )
        for file_name in self._interesting_repo_files():
            add_candidate(
                description=f"Review current behavior in {file_name}",
                group="repo_signals",
                rationale="Surfaced from repository files that look behaviorally sensitive.",
            )
        if brief.source_of_truth:
            add_candidate(
                description=f"Validate behavior against {brief.source_of_truth}",
                group="source_of_truth",
                rationale="Surfaced from the operator's named source of truth.",
            )

        groups: list[BrownfieldReviewGroup] = []
        for group_key in _BROWNFIELD_GROUP_ORDER:
            items = [
                BrownfieldReviewCandidate(
                    description=entry["description"],
                    primary_group=entry["primary_group"],
                    rationale=entry["rationale"],
                    secondary_groups=tuple(entry["secondary_groups"]),
                )
                for entry in grouped_candidates.values()
                if entry["primary_group"] == group_key
            ]
            if items:
                groups.append(
                    BrownfieldReviewGroup(
                        key=group_key,
                        label=_BROWNFIELD_GROUP_LABELS[group_key],
                        items=items,
                    )
                )
        return groups

    def discover_brownfield_candidates(self, brief: BuilderBriefDraft) -> list[str]:
        candidates: list[str] = []
        for group in self.build_brownfield_review_groups(brief):
            candidates.extend(item.description for item in group.items)
        return candidates[:5]

    def _normalize_review_state(
        self,
        brief: BuilderBriefDraft,
        review_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        groups = self.build_brownfield_review_groups(brief)
        if review_state is None:
            return {
                "groups": groups,
                "group_index": 0,
                "item_index": 0,
                "reviewed_candidates": [],
                "reviewed_entry_ids": [],
                "group_defaults": {},
            }

        serialized_groups = review_state.get("groups") or []
        if serialized_groups:
            groups = [
                BrownfieldReviewGroup(
                    key=group["key"],
                    label=group["label"],
                    items=[
                        BrownfieldReviewCandidate(
                            description=item["description"],
                            primary_group=item["primary_group"],
                            rationale=item["rationale"],
                            secondary_groups=tuple(item.get("secondary_groups", [])),
                        )
                        for item in group["items"]
                    ],
                )
                for group in serialized_groups
            ]

        return {
            "groups": groups,
            "group_index": int(review_state.get("group_index", 0)),
            "item_index": int(review_state.get("item_index", 0)),
            "reviewed_candidates": list(review_state.get("reviewed_candidates", [])),
            "reviewed_entry_ids": list(review_state.get("reviewed_entry_ids", [])),
            "group_defaults": dict(review_state.get("group_defaults", {})),
        }

    def _review_checkpoint(
        self,
        state: dict[str, Any],
        *,
        group_index: int,
        item_index: int,
        reviewed_candidates: dict[str, str],
        reviewed_entry_ids: list[str],
        group_defaults: dict[str, str],
    ) -> dict[str, Any]:
        total_candidates = sum(len(group.items) for group in state["groups"])
        return {
            "groups": [self._serialize_group(group) for group in state["groups"]],
            "group_index": group_index,
            "item_index": item_index,
            "reviewed_candidates": [
                {"description": description, "disposition": disposition}
                for description, disposition in reviewed_candidates.items()
            ],
            "reviewed_entry_ids": list(reviewed_entry_ids),
            "reviewed_count": len(reviewed_entry_ids),
            "remaining_count": max(total_candidates - len(reviewed_candidates), 0),
            "entry_reviewed_count": len(reviewed_entry_ids),
            "item_reviewed_count": len(reviewed_candidates),
            "item_remaining_count": max(total_candidates - len(reviewed_candidates), 0),
            "group_defaults": dict(group_defaults),
        }

    @staticmethod
    def _advance_review_position(
        *,
        groups: list[BrownfieldReviewGroup],
        group_index: int,
        item_index: int,
    ) -> tuple[int, int]:
        if item_index + 1 < len(groups[group_index].items):
            return group_index, item_index + 1
        if group_index + 1 < len(groups):
            return group_index + 1, 0
        return len(groups), 0

    @staticmethod
    def _serialize_group(group: BrownfieldReviewGroup) -> dict[str, Any]:
        return {
            "key": group.key,
            "label": group.label,
            "items": [asdict(item) for item in group.items],
        }

    @staticmethod
    def _build_review_prompt(
        candidate: BrownfieldReviewCandidate,
        *,
        group: BrownfieldReviewGroup,
    ) -> str:
        sources = ", ".join(candidate.secondary_groups)
        if sources:
            sources = f" | Also surfaced via: {sources}"
        return (
            f"{group.label}: {candidate.description}\n"
            f"Why CES surfaced this: {candidate.rationale}{sources}\n"
            "Disposition"
        )

    def export_prl_draft(self, *, brief_id: str, brief: BuilderBriefDraft) -> Path:
        export_dir = self._project_root / ".ces" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"prl-draft-{brief_id.lower()}.md"
        lines = [
            f"# PRL Draft for {brief.request}",
            "",
            "## Request",
            brief.request,
            "",
            "## Project Mode",
            brief.project_mode,
            "",
            "## Constraints",
            *_as_bullets(brief.constraints),
            "",
            "## Acceptance Criteria",
            *_as_bullets(brief.acceptance_criteria),
            "",
            "## Must Not Break",
            *_as_bullets(brief.must_not_break),
        ]
        if brief.source_of_truth:
            lines.extend(
                [
                    "",
                    "## Brownfield Source Of Truth",
                    brief.source_of_truth,
                ]
            )
        if brief.critical_flows:
            lines.extend(
                [
                    "",
                    "## Critical Flows",
                    *_as_bullets(brief.critical_flows),
                ]
            )
        export_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return export_path

    def _has_repo_files(self) -> bool:
        ignored_roots = {".ces", ".git", ".gitignore", ".hg", ".svn", "__pycache__"}
        for path in self._project_root.iterdir():
            if path.name in ignored_roots:
                continue
            if path.is_file():
                return True
            if any(child.is_file() for child in path.rglob("*")):
                return True
        return False

    def _interesting_repo_files(self) -> list[str]:
        keywords = ("billing", "invoice", "export", "csv", "auth", "payment")
        file_names = [
            path.name for path in self._project_root.iterdir() if path.is_file() and not path.name.startswith(".")
        ]
        ranked = sorted(
            file_names,
            key=lambda name: (
                0 if any(keyword in name.lower() for keyword in keywords) else 1,
                name,
            ),
        )
        return ranked[:2]


def _split_list(raw: str) -> list[str]:
    """Split operator-entered list text without breaking comma-rich criteria.

    `ces build --acceptance ...` passes each option value through as a distinct
    newline-delimited item before it reaches this helper. Splitting those items
    again on commas corrupts normal acceptance criteria such as "add, list,
    render, delete, export commands". Preserve lines as atomic items and keep
    semicolons as the compact inline separator for prompt-mode multi-entry text.
    """
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    for line in normalized.split("\n"):
        parts.extend(part.strip() for part in line.split(";") if part.strip())
    return parts


def _as_bullets(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values] or ["- None captured yet"]


def _split_flows(raw: str) -> list[str]:
    """Split critical-flow text without corrupting comma-rich workflow descriptions.

    Repeated ``--critical-flow`` options arrive as newline-delimited values.
    Treat each line as atomic, matching ``_split_list`` behavior for acceptance
    criteria, and reserve semicolons for compact prompt-mode multi-entry text.
    """
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    flows: list[str] = []
    for line in normalized.split("\n"):
        flows.extend(part.strip() for part in line.split(";") if part.strip())
    return flows


def _normalize_disposition(value: str) -> str:
    disposition = value.strip().lower()
    if disposition not in _DISPOSITION_VALUES:
        return LegacyDisposition.UNDER_INVESTIGATION.value
    return disposition
