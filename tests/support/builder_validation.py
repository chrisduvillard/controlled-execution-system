"""Helpers for exporting builder validation evidence artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BuilderValidationArtifactReport:
    markdown_path: Path
    json_path: Path


def export_builder_validation_artifacts(
    *,
    output_dir: Path,
    milestone: str,
    records: list[tuple[Any, Any]],
) -> BuilderValidationArtifactReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = milestone.lower().replace(".", "-")
    markdown_path = output_dir / f"{slug}-builder-validation.md"
    json_path = output_dir / f"{slug}-builder-validation.json"

    serialized = [_serialize_record(scenario, result) for scenario, result in records]
    payload = {"milestone": milestone, "records": serialized}

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(milestone, serialized), encoding="utf-8")
    return BuilderValidationArtifactReport(
        markdown_path=markdown_path,
        json_path=json_path,
    )


def _serialize_record(scenario: Any, result: Any) -> dict[str, Any]:
    snapshot = result.latest_snapshot
    manifest = getattr(snapshot, "manifest", None)
    evidence = getattr(snapshot, "evidence", None)
    approval = getattr(snapshot, "approval", None)
    runtime = getattr(snapshot, "runtime_execution", None)
    brownfield = getattr(snapshot, "brownfield", None)
    return {
        "scenario_name": scenario.name,
        "request": getattr(snapshot, "request", scenario.request),
        "project_mode": getattr(snapshot, "project_mode", "unknown"),
        "fixture_name": scenario.fixture_name,
        "project_root": str(result.project_root),
        "latest_artifact": getattr(snapshot, "latest_artifact", None),
        "latest_activity": getattr(snapshot, "latest_activity", None),
        "next_step": getattr(snapshot, "next_step", None),
        "is_chain_complete": bool(getattr(snapshot, "is_chain_complete", False)),
        "manifest_id": getattr(manifest, "manifest_id", None),
        "evidence_packet_id": evidence.get("packet_id") if isinstance(evidence, dict) else None,
        "approval_decision": getattr(approval, "decision", None),
        "runtime_exit_code": getattr(runtime, "exit_code", None),
        "reported_model": getattr(runtime, "reported_model", None),
        "brownfield_reviewed_count": getattr(brownfield, "reviewed_count", 0) if brownfield is not None else 0,
        "brownfield_remaining_count": getattr(brownfield, "remaining_count", 0) if brownfield is not None else 0,
        "runtime_retry_preserved_review_count": bool(result.runtime_retry_preserved_review_count),
    }


def _render_markdown(milestone: str, records: list[dict[str, Any]]) -> str:
    lines = [
        f"# Builder Validation Artifacts — {milestone}",
        "",
        "| Scenario | Request | Mode | Latest Artifact | Chain Complete | Approval |",
        "|----------|---------|------|-----------------|----------------|----------|",
    ]
    for record in records:
        lines.append(
            "| "
            f"{record['scenario_name']} | "
            f"{record['request']} | "
            f"{record['project_mode']} | "
            f"{record['latest_artifact']} | "
            f"{'yes' if record['is_chain_complete'] else 'no'} | "
            f"{record['approval_decision']} |"
        )

    for record in records:
        lines.extend(
            [
                "",
                f"## {record['scenario_name']}",
                "",
                f"- Request: {record['request']}",
                f"- Project mode: {record['project_mode']}",
                f"- Fixture: {record['fixture_name'] or 'none (greenfield empty fixture)'}",
                f"- Latest activity: {record['latest_activity']}",
                f"- Next step: {record['next_step']}",
                f"- Manifest ID: {record['manifest_id']}",
                f"- Evidence packet: {record['evidence_packet_id']}",
                f"- Approval: {record['approval_decision']}",
                f"- Runtime exit code: {record['runtime_exit_code']}",
            ]
        )
        if record["project_mode"] == "brownfield":
            lines.extend(
                [
                    f"- Brownfield progress: {record['brownfield_reviewed_count']} reviewed, "
                    f"{record['brownfield_remaining_count']} remaining",
                    "- Runtime retry preserved review count: "
                    f"{'yes' if record['runtime_retry_preserved_review_count'] else 'no'}",
                ]
            )

    return "\n".join(lines) + "\n"
