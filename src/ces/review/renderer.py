"""Markdown renderers for semantic review artifacts."""

from __future__ import annotations

from ces.execution.secrets import scrub_secrets_from_text
from ces.review.models import IntentCoverageMap, ReviewArtifactBundle, ReviewPath, RiskMap, VerificationSummary


def render_review_brief(bundle: ReviewArtifactBundle) -> str:
    """Render the canonical Markdown Review Brief."""

    metadata = bundle.metadata
    changed_by_area = _changed_by_area(bundle)
    review_first = _review_first(bundle.risk_map)
    coverage = render_intent_coverage(bundle.intent_coverage).strip()
    risk = _risk_markdown(bundle.risk_map)
    verification = _verification_markdown(bundle.verification_summary)
    provenance = bundle.agent_provenance
    raw_links = "\n".join(f"- `{name}`: `{path}`" for name, path in sorted(metadata.artifact_paths.items()))
    markdown = f"""# CES Review Brief: {metadata.review_id}

## Bottom Line
{_bottom_line(bundle)}

## Objective
{bundle.intent_coverage.objective or "No source objective was available; this is a local diff review."}

## What Changed
{changed_by_area}

## Review This First
{review_first}

## Architecture and Behavior Impact
{_impact(bundle)}

## Intent Coverage
{coverage}

## Risk Map
{risk}

## Verification Evidence
{verification}

## Agent Provenance and Assumptions
- Mode: `{provenance.mode}`
- Build: `{provenance.build_id or "unknown"}`
- Manifest: `{provenance.manifest_id or "unknown"}`
- Limitations: {", ".join(provenance.limitations) if provenance.limitations else "None recorded."}

## Human Review Checklist
{_checklist(bundle)}

## Not Changed / Deferred
{_deferred(bundle)}

## Raw Artifact Links
{raw_links or "- No artifact paths recorded."}
"""
    return scrub_secrets_from_text(markdown).rstrip() + "\n"


def render_intent_coverage(coverage: IntentCoverageMap) -> str:
    if not coverage.items:
        return "- No intent items were available; coverage is unknown."
    return "\n".join(
        f"- {item.requirement_id}: **{item.status}** via {_via(item.changed_files, item.verification_refs)}"
        + (f" — {item.notes[0]}" if item.notes else "")
        for item in coverage.items
    )


def render_review_path(review_path: ReviewPath) -> str:
    lines = ["# Review Path", ""]
    for step in review_path.steps:
        lines.append(f"{step.order}. `{step.target}` - {step.reason} ({step.risk_level})")
        for checkpoint in step.checkpoints:
            lines.append(f"   - [ ] {checkpoint}")
    if review_path.checkpoints:
        lines.extend(["", "## Checkpoints", ""])
        lines.extend(f"- [ ] {checkpoint}" for checkpoint in review_path.checkpoints)
    return scrub_secrets_from_text("\n".join(lines).rstrip() + "\n")


def _bottom_line(bundle: ReviewArtifactBundle) -> str:
    risk = bundle.risk_map.overall_level
    verification = bundle.verification_summary.status
    stale = " The artifact is stale; regenerate before approval." if bundle.metadata.stale else ""
    if verification in {"failed", "skipped", "not_run", "unknown"} and risk in {"high", "critical"}:
        return f"High-attention review required: risk is **{risk}** and verification is **{verification}**.{stale}"
    return f"Reviewable local diff: risk is **{risk}** and verification is **{verification}**.{stale}"


def _changed_by_area(bundle: ReviewArtifactBundle) -> str:
    grouped: dict[str, list[str]] = {}
    for file in bundle.diff_index.changed_files:
        area = file.classification.conceptual_area
        grouped.setdefault(area, []).append(
            f"`{file.path}` ({file.status}, +{file.additions}/-{file.deletions}, {file.classification.role})"
        )
    if not grouped:
        return "- No changed files detected."
    lines: list[str] = []
    for area in sorted(grouped):
        lines.append(f"- **{area}**")
        lines.extend(f"  - {entry}" for entry in sorted(grouped[area]))
    return "\n".join(lines)


def _review_first(risk_map: RiskMap) -> str:
    if not risk_map.review_first:
        return "1. No changed files - confirm the requested diff is correct."
    return "\n".join(
        f"{index}. `{item.path}` - {item.signals[0].reason if item.signals else 'Changed file.'}"
        for index, item in enumerate(risk_map.review_first[:5], start=1)
    )


def _impact(bundle: ReviewArtifactBundle) -> str:
    areas = ", ".join(area.area for area in bundle.risk_map.area_risks[:6]) or "none"
    operations = sorted({file.status for file in bundle.diff_index.changed_files})
    return f"Changed conceptual areas: {areas}. File operations: {', '.join(operations) if operations else 'none'}. Repository content is summarized as untrusted data."


def _risk_markdown(risk_map: RiskMap) -> str:
    by_level: dict[str, list[str]] = {"critical": [], "high": [], "medium": [], "low": []}
    for item in risk_map.file_risks:
        by_level[item.level].append(f"`{item.path}` ({item.score})")
    lines = [f"- Overall: **{risk_map.overall_level}** ({risk_map.overall_score})"]
    for level in ("critical", "high", "medium", "low"):
        values = ", ".join(by_level[level][:6]) if by_level[level] else "None"
        lines.append(f"- {level.title()}: {values}")
    for warning in risk_map.warnings:
        lines.append(f"- Warning: {warning}")
    return "\n".join(lines)


def _verification_markdown(summary: VerificationSummary) -> str:
    if not summary.commands:
        return f"- Verification status: **{summary.status}**\n- Evidence: {', '.join(summary.evidence_sources) if summary.evidence_sources else 'none'}"
    return "\n".join(f"- `{command.command}`: **{command.status}** {command.summary}" for command in summary.commands)


def _checklist(bundle: ReviewArtifactBundle) -> str:
    checkpoints = bundle.review_path.checkpoints or bundle.risk_map.checkpoints
    if not checkpoints:
        checkpoints = ("Are tests proving the new behavior rather than only implementation details?",)
    return "\n".join(f"- [ ] {checkpoint}" for checkpoint in checkpoints[:8])


def _deferred(bundle: ReviewArtifactBundle) -> str:
    deferred = [
        item for item in bundle.intent_coverage.items if item.status in {"intentionally_deferred", "not_applicable"}
    ]
    if deferred:
        return "\n".join(f"- {item.requirement_id}: {item.text}" for item in deferred)
    return "- No deferred scope was identified from available metadata."


def _via(files: tuple[str, ...], commands: tuple[str, ...]) -> str:
    refs = [*(f"`{file}`" for file in files[:4]), *(f"`{command}`" for command in commands[:2])]
    return ", ".join(refs) if refs else "no deterministic evidence"
