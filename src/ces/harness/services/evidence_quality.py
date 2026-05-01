"""Evidence quality state computation for CLI summaries and reports."""

from __future__ import annotations

from typing import Any

EVIDENCE_QUALITY_STATES = ("complete", "missing_artifacts", "manual_only", "waived", "failed")


def compute_evidence_quality_state(evidence: dict[str, Any] | None) -> str:
    """Collapse evidence content into a compact operator-facing state."""
    if not evidence:
        return "manual_only"
    content = evidence.get("content") if isinstance(evidence.get("content"), dict) else evidence
    sensor_policy = content.get("sensor_policy", {}) if isinstance(content, dict) else {}
    blocking = sensor_policy.get("blocking") if isinstance(sensor_policy, dict) else None
    if blocking:
        return "failed"

    sensors = content.get("sensors", []) if isinstance(content, dict) else []
    for sensor in sensors:
        if _sensor_has_missing_artifact(sensor):
            return "missing_artifacts"
        if isinstance(sensor, dict) and sensor.get("passed") is False:
            return "failed"

    runtime_safety = content.get("runtime_safety", {}) if isinstance(content, dict) else {}
    if isinstance(runtime_safety, dict) and runtime_safety.get("accepted_runtime_side_effect_risk"):
        return "waived"
    content_manual_only = bool(content.get("manual_review_only")) if isinstance(content, dict) else False
    if evidence.get("manual_review_only") or content_manual_only:
        return "manual_only"
    return "complete"


def _sensor_has_missing_artifact(sensor: Any) -> bool:
    findings = sensor.get("findings", []) if isinstance(sensor, dict) else getattr(sensor, "findings", [])
    for finding in findings or []:
        category = finding.get("category") if isinstance(finding, dict) else getattr(finding, "category", None)
        if category == "missing_artifact":
            return True
    return False
