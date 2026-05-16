"""Execution-contract intake models and deterministic source normalization.

This module is intentionally narrow. CES accepts inline intent text, local
Markdown/PRD files, and GitHub issues. It does not import framework-specific
layouts from spec-kit, OpenSpec, BMAD, GSD, or other methodology projects.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from ces.control.models.spec import Risk, SignalHints, SpecDocument, SpecFrontmatter, Story
from ces.harness.services.spec_authoring import render_markdown
from ces.shared.base import CESBaseModel

_NEXT_COMMANDS = ("ces build --from-contract", "ces verify", "ces proof", "ces approve")
_DEFAULT_OWNER = "cli-user"


class ContractSourceKind(str, Enum):
    """Stable source boundaries supported by ``ces intake``."""

    INLINE = "inline"
    PRD = "prd"
    GITHUB_ISSUE = "github_issue"


class ValidationSeverity(str, Enum):
    """Contract validation severity."""

    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class RequiredEvidenceKind(str, Enum):
    """Evidence categories CES can demand before approval."""

    COMMAND = "command"
    TEST = "test"
    ARTIFACT = "artifact"
    MANUAL_INSPECTION = "manual_inspection"


class ContractSource(CESBaseModel):
    """Original source used to build an execution contract."""

    kind: ContractSourceKind
    label: str
    content: str
    path: str | None = None
    url: str | None = None
    external_id: str | None = None
    content_hash: str | None = None


class BehaviorDelta(CESBaseModel):
    """OpenSpec-inspired behavior categories for brownfield safety."""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    def has_signal(self) -> bool:
        """Return whether any behavior-delta category contains information."""

        return any((self.added, self.modified, self.removed, self.preserved, self.unknown))


class RequiredEvidence(CESBaseModel):
    """Evidence requirement attached to an execution contract."""

    description: str
    kind: RequiredEvidenceKind = RequiredEvidenceKind.TEST
    required: bool = True


class ContractValidationFinding(CESBaseModel):
    """Machine-readable validation finding for an execution contract."""

    severity: ValidationSeverity
    message: str
    field: str | None = None


class ExecutionContract(CESBaseModel):
    """Canonical CES artifact between intake and governed execution."""

    schema_version: Literal["1.0"] = "1.0"
    contract_id: str
    source: ContractSource
    objective: str
    problem: str
    acceptance_criteria: tuple[str, ...]
    non_goals: tuple[str, ...]
    behavior_delta: BehaviorDelta
    required_evidence: tuple[RequiredEvidence, ...]
    risks: tuple[Risk, ...] = ()
    policies: tuple[str, ...] = ("verification-before-completion",)
    owner: str = _DEFAULT_OWNER
    created_at: datetime
    next_commands: tuple[str, ...] = _NEXT_COMMANDS
    generated_spec_path: str | None = None

    def to_markdown(self) -> str:
        """Render a compact human-reviewable execution contract."""

        lines = [
            "# Execution Contract",
            "",
            f"Contract ID: `{self.contract_id}`",
            f"Source: {self.source.label}",
            f"Objective: {self.objective}",
            "",
            "## Problem",
            self.problem,
            "",
            "## Acceptance Criteria",
            *_bullets(self.acceptance_criteria),
            "",
            "## Non-Goals",
            *_bullets(self.non_goals),
            "",
            "## Behavior Delta",
            *_behavior_markdown(self.behavior_delta),
            "",
            "## Required Evidence",
            *_bullets(item.description for item in self.required_evidence),
            "",
            "## Policies",
            *_bullets(self.policies),
            "",
            "## Next Commands",
            *_bullets(f"`{command}`" for command in self.next_commands),
            "",
        ]
        return "\n".join(lines)

    def to_spec_document(self) -> SpecDocument:
        """Convert this contract into the existing CES spec/decompose model."""

        spec_id = self.contract_id.replace("EC-", "SP-", 1)
        title = self.objective[:120]
        risk_hint: Literal["A", "B", "C"] | None = "B" if _is_high_attention_contract(self) else None
        return SpecDocument(
            frontmatter=SpecFrontmatter(
                spec_id=spec_id,
                title=title,
                owner=self.owner,
                created_at=self.created_at,
                status="draft",
                template="intake-execution-contract",
                signals=SignalHints(
                    primary_change_class=_infer_change_class(self.objective),
                    blast_radius_hint="module" if _is_high_attention_contract(self) else "isolated",
                    touches_data=_contains_any(self.objective, ("data", "database", "csv", "export", "import")),
                    touches_auth=_contains_any(self.objective, ("auth", "login", "permission", "role")),
                    touches_billing=_contains_any(self.objective, ("billing", "invoice", "payment", "subscription")),
                ),
            ),
            problem=self.problem,
            users="Primary users and operators affected by the requested change.",
            success_criteria=self.acceptance_criteria,
            non_goals=self.non_goals,
            risks=self.risks,
            stories=(
                Story(
                    story_id=f"ST-{self.contract_id.removeprefix('EC-')}",
                    title=title,
                    description=_story_description(self),
                    acceptance_criteria=self.acceptance_criteria,
                    depends_on=(),
                    size="M" if _is_high_attention_contract(self) else "S",
                    risk=risk_hint,
                ),
            ),
            rollback_plan="Revert the implementation commit or restore the pre-change behavior if required evidence fails.",
        )


@dataclass(frozen=True)
class SavedExecutionContract:
    """Paths written for an execution contract."""

    contract: ExecutionContract
    json_path: Path
    markdown_path: Path
    latest_path: Path
    spec_path: Path


class SourceReader:
    """Read supported intake sources."""

    def read_inline(self, text: str) -> ContractSource:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("inline intake text cannot be empty")
        return ContractSource(
            kind=ContractSourceKind.INLINE,
            label="inline intent",
            content=cleaned,
            content_hash=_sha256(cleaned),
        )

    def read_prd(self, path: str | Path, *, project_root: str | Path | None = None) -> ContractSource:
        root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = (root / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if not resolved.is_file():
            raise ValueError(f"PRD file not found: {path}")
        if resolved.suffix.lower() not in {".md", ".markdown"}:
            raise ValueError("ces intake only accepts Markdown PRD files")
        content = resolved.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("PRD file is empty")
        return ContractSource(
            kind=ContractSourceKind.PRD,
            label=resolved.name,
            content=content,
            path=str(resolved),
            content_hash=_sha256(content),
        )

    def read_github_issue(self, issue: str) -> ContractSource:
        issue_ref = issue.strip()
        if not issue_ref:
            raise ValueError("GitHub issue reference cannot be empty")
        gh_path = shutil.which("gh")
        if gh_path is None:
            raise RuntimeError("GitHub issue intake requires the GitHub CLI (`gh`) on PATH.")
        completed = subprocess.run(  # noqa: S603
            [gh_path, "issue", "view", issue_ref, "--json", "number,title,body,url"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or "gh issue view failed"
            raise RuntimeError(f"Could not read GitHub issue {issue_ref}: {stderr}")
        payload = json.loads(completed.stdout)
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body") or "").strip()
        number = payload.get("number") or issue_ref
        url = str(payload.get("url") or "").strip() or None
        content = f"# {title}\n\n{body}".strip()
        return ContractSource(
            kind=ContractSourceKind.GITHUB_ISSUE,
            label=f"GitHub issue #{number}",
            content=content,
            url=url,
            external_id=str(number),
            content_hash=_sha256(content),
        )


class IntakeNormalizer:
    """Deterministically normalize supported sources into execution contracts."""

    def __init__(self, source_reader: SourceReader | None = None) -> None:
        self._source_reader = source_reader or SourceReader()

    def from_inline(self, text: str, *, project_root: str | Path | None = None) -> ExecutionContract:
        return self.from_source(self._source_reader.read_inline(text), project_root=project_root)

    def from_prd(self, path: str | Path, *, project_root: str | Path | None = None) -> ExecutionContract:
        return self.from_source(
            self._source_reader.read_prd(path, project_root=project_root), project_root=project_root
        )

    def from_github_issue(self, issue: str, *, project_root: str | Path | None = None) -> ExecutionContract:
        return self.from_source(self._source_reader.read_github_issue(issue), project_root=project_root)

    def from_source(
        self,
        source: ContractSource,
        *,
        project_root: str | Path | None = None,
    ) -> ExecutionContract:
        sections = _parse_markdown_sections(source.content)
        title = _first_heading(source.content) or _first_line(source.content)
        objective = _clean_sentence(title)
        problem = _section_text(sections, "problem") or _section_text(sections, "background") or objective
        acceptance = _section_bullets(sections, "success criteria", "acceptance criteria", "requirements")
        if not acceptance:
            acceptance = (objective,)
        non_goals = _section_bullets(sections, "non-goals", "non goals", "out of scope")
        if not non_goals:
            non_goals = (f"Do not expand scope beyond: {objective}",)
        behavior_delta = BehaviorDelta(
            added=_section_bullets(sections, "added behavior", "added"),
            modified=_section_bullets(sections, "modified behavior", "modified"),
            removed=_section_bullets(sections, "removed behavior", "removed"),
            preserved=_section_bullets(sections, "preserved behavior", "unchanged behavior", "must not change")
            or ("Preserve existing behavior unless explicitly changed.",),
            unknown=_section_bullets(sections, "unknown behavior", "unknown/unverified behavior"),
        )
        evidence = tuple(
            RequiredEvidence(description=item, kind=_evidence_kind(item))
            for item in _section_bullets(sections, "required evidence", "evidence", "verification")
        ) or _default_evidence(objective)
        risks = _risks_from_sections(sections)
        return ExecutionContract(
            contract_id=_new_contract_id(source, project_root=project_root),
            source=source,
            objective=objective,
            problem=problem,
            acceptance_criteria=acceptance,
            non_goals=non_goals,
            behavior_delta=behavior_delta,
            required_evidence=evidence,
            risks=risks,
            created_at=datetime.now(timezone.utc),
        )


class ExecutionContractRepository:
    """Project-local repository for execution contracts."""

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()

    def save(self, contract: ExecutionContract) -> SavedExecutionContract:
        ces_dir = self.project_root / ".ces"
        if ces_dir.is_symlink():
            raise ValueError("Refusing to write contracts through symlinked .ces")
        contracts_dir = ces_dir / "contracts"
        docs_dir = self.project_root / "docs" / "contracts"
        specs_dir = self.project_root / "docs" / "specs"
        for directory in (contracts_dir, docs_dir, specs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        spec_path = specs_dir / f"{contract.contract_id}.md"
        contract = contract.model_copy(update={"generated_spec_path": str(spec_path.relative_to(self.project_root))})
        json_path = contracts_dir / f"{contract.contract_id}.json"
        markdown_path = docs_dir / f"{contract.contract_id}.md"
        latest_path = contracts_dir / "latest.json"
        payload = contract.model_dump(mode="json")
        json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        json_path.write_text(json_text, encoding="utf-8")
        latest_path.write_text(json_text, encoding="utf-8")
        markdown_path.write_text(contract.to_markdown(), encoding="utf-8")
        spec_path.write_text(render_markdown(contract.to_spec_document()), encoding="utf-8")
        return SavedExecutionContract(
            contract=contract,
            json_path=json_path,
            markdown_path=markdown_path,
            latest_path=latest_path,
            spec_path=spec_path,
        )

    def load_latest(self) -> ExecutionContract:
        path = self.project_root / ".ces" / "contracts" / "latest.json"
        if not path.is_file():
            raise ValueError("No intake execution contract found. Run `ces intake ...` first.")
        return ExecutionContract.model_validate_json(path.read_text(encoding="utf-8"))

    def load(self, contract_id: str) -> ExecutionContract:
        path = self.project_root / ".ces" / "contracts" / f"{contract_id}.json"
        if not path.is_file():
            raise ValueError(f"Execution contract not found: {contract_id}")
        return ExecutionContract.model_validate_json(path.read_text(encoding="utf-8"))


def validate_execution_contract(contract: ExecutionContract) -> tuple[ContractValidationFinding, ...]:
    """Return deterministic validation findings for approval safety."""

    findings: list[ContractValidationFinding] = []
    if not contract.objective.strip():
        findings.append(
            ContractValidationFinding(
                severity=ValidationSeverity.BLOCKER,
                field="objective",
                message="Execution contract objective is required.",
            )
        )
    if not contract.acceptance_criteria:
        findings.append(
            ContractValidationFinding(
                severity=ValidationSeverity.BLOCKER,
                field="acceptance_criteria",
                message="Execution contract must include acceptance criteria.",
            )
        )
    if not contract.required_evidence:
        findings.append(
            ContractValidationFinding(
                severity=ValidationSeverity.BLOCKER,
                field="required_evidence",
                message="Execution contract must include required evidence before approval.",
            )
        )
    if not contract.behavior_delta.has_signal():
        findings.append(
            ContractValidationFinding(
                severity=ValidationSeverity.WARNING,
                field="behavior_delta",
                message="Execution contract has no behavior delta; brownfield safety may be under-specified.",
            )
        )
    if not contract.policies:
        findings.append(
            ContractValidationFinding(
                severity=ValidationSeverity.WARNING,
                field="policies",
                message="Execution contract has no policy modules attached.",
            )
        )
    return tuple(findings)


def _new_contract_id(source: ContractSource, *, project_root: str | Path | None) -> str:
    root = str(Path(project_root).resolve()) if project_root is not None else str(Path.cwd().resolve())
    seed = f"{root}\n{source.kind.value}\n{source.path or source.url or source.label}\n{source.content_hash or source.content}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()
    return f"EC-{digest}-{uuid.uuid4().hex[:4].upper()}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_markdown_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "body"
    sections[current] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            current = _normalize_heading(match.group(2))
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return None


def _first_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().strip("# ").strip()
        if cleaned:
            return cleaned
    return "Untitled intake request"


def _clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(".")


def _section_text(sections: dict[str, str], *names: str) -> str:
    for name in names:
        value = sections.get(_normalize_heading(name), "").strip()
        if value:
            return value
    return ""


def _section_bullets(sections: dict[str, str], *names: str) -> tuple[str, ...]:
    text = _section_text(sections, *names)
    if not text:
        return ()
    bullets: list[str] = []
    pending: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if pending:
                bullets.append(" ".join(pending).strip())
                pending = []
            continue
        match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if match:
            if pending:
                bullets.append(" ".join(pending).strip())
                pending = []
            bullets.append(match.group(1).strip())
        else:
            pending.append(line)
    if pending:
        bullets.append(" ".join(pending).strip())
    return tuple(item for item in bullets if item)


def _risks_from_sections(sections: dict[str, str]) -> tuple[Risk, ...]:
    risks = []
    for item in _section_bullets(sections, "risks", "risks mitigations", "risks and mitigations"):
        risk, sep, mitigation = item.partition("::")
        risks.append(Risk(risk=risk.strip(), mitigation=mitigation.strip() if sep else "Verify before approval."))
    return tuple(risks)


def _default_evidence(objective: str) -> tuple[RequiredEvidence, ...]:
    return (
        RequiredEvidence(
            description=f"Fresh verification command proves: {objective}", kind=RequiredEvidenceKind.COMMAND
        ),
        RequiredEvidence(
            description="Proof card marks no required evidence as missing", kind=RequiredEvidenceKind.ARTIFACT
        ),
    )


def _evidence_kind(item: str) -> RequiredEvidenceKind:
    lowered = item.lower()
    if "manual" in lowered or "inspect" in lowered:
        return RequiredEvidenceKind.MANUAL_INSPECTION
    if "artifact" in lowered or "file" in lowered or "sample" in lowered:
        return RequiredEvidenceKind.ARTIFACT
    if "command" in lowered or "run" in lowered:
        return RequiredEvidenceKind.COMMAND
    return RequiredEvidenceKind.TEST


def _bullets(items: Any) -> list[str]:
    values = [str(item) for item in items if str(item).strip()]
    return [f"- {item}" for item in values] or ["- None recorded."]


def _behavior_markdown(delta: BehaviorDelta) -> list[str]:
    lines: list[str] = []
    for label, items in (
        ("Added", delta.added),
        ("Modified", delta.modified),
        ("Removed", delta.removed),
        ("Preserved", delta.preserved),
        ("Unknown", delta.unknown),
    ):
        lines.append(f"### {label}")
        lines.extend(_bullets(items))
        lines.append("")
    return lines[:-1]


def _infer_change_class(objective: str) -> Literal["feature", "bug", "refactor", "infra", "doc"]:
    lowered = objective.lower()
    if _contains_any(lowered, ("fix", "bug", "regression")):
        return "bug"
    if _contains_any(lowered, ("doc", "readme", "documentation")):
        return "doc"
    if _contains_any(lowered, ("ci", "deploy", "infra", "pipeline")):
        return "infra"
    if _contains_any(lowered, ("refactor", "cleanup")):
        return "refactor"
    return "feature"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _is_high_attention_contract(contract: ExecutionContract) -> bool:
    joined = " ".join(
        (
            contract.objective,
            contract.problem,
            " ".join(contract.acceptance_criteria),
            " ".join(contract.behavior_delta.modified),
            " ".join(contract.behavior_delta.removed),
        )
    )
    return _contains_any(joined, ("auth", "billing", "invoice", "data", "database", "migration", "security"))


def _story_description(contract: ExecutionContract) -> str:
    parts = [contract.problem, "", "Behavior delta:"]
    for label, items in (
        ("added", contract.behavior_delta.added),
        ("modified", contract.behavior_delta.modified),
        ("removed", contract.behavior_delta.removed),
        ("preserved", contract.behavior_delta.preserved),
        ("unknown", contract.behavior_delta.unknown),
    ):
        if items:
            parts.append(f"- {label}: {'; '.join(items)}")
    parts.append("")
    parts.append("Required evidence:")
    parts.extend(f"- {item.description}" for item in contract.required_evidence)
    return "\n".join(parts).strip()
