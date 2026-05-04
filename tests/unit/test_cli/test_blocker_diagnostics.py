"""Tests for builder blocker diagnostics."""

from __future__ import annotations

from ces.cli._builder_report import BuilderRunReport


def _report(**overrides: object) -> BuilderRunReport:
    defaults: dict[str, object] = {
        "session_id": "BS-1",
        "request": "Build PromptVault",
        "project_mode": "greenfield",
        "stage": "completed",
        "review_state": "rejected",
        "latest_outcome": "rejected",
        "latest_activity": "CES recorded the latest review decision.",
        "next_step": "Review evidence.",
        "latest_artifact": "approval",
        "manifest_id": "M-1",
        "evidence_packet_id": "EP-1",
        "approval_decision": "reject",
        "workflow_state": "rejected",
        "triage_color": "red",
        "evidence_quality_state": "missing_artifacts",
        "verification_sensor_state": "none_configured_expert_opt_out",
        "runtime_tool_allowlist_enforced": None,
        "runtime_side_effect_waived": False,
        "mcp_grounding_supported": None,
        "prl_draft_path": None,
        "reported_model": "gpt-test",
        "verification_findings": (),
        "independent_verification_passed": None,
        "completion_contract_path": None,
        "manual_completion_supersedes_rejected_auto_review": False,
        "brownfield_reviewed_count": 0,
        "brownfield_remaining_count": 0,
    }
    defaults.update(overrides)
    return BuilderRunReport(**defaults)  # type: ignore[arg-type]


def test_diagnostic_maps_missing_evidence_to_recover_command() -> None:
    from ces.cli._blocker_diagnostics import diagnose_builder_report

    diagnostic = diagnose_builder_report(_report())

    assert diagnostic.category == "evidence_missing_artifacts"
    assert diagnostic.product_may_be_complete is True
    assert "missing_artifacts" in diagnostic.reason
    assert diagnostic.next_command == "ces recover --dry-run"


def test_diagnostic_maps_runtime_failure_to_doctor_command() -> None:
    from ces.cli._blocker_diagnostics import diagnose_builder_report

    diagnostic = diagnose_builder_report(
        _report(
            stage="runtime_failed",
            latest_outcome="runtime_failed",
            evidence_quality_state="missing_packet",
            reported_model="codex",
        )
    )

    assert diagnostic.category == "runtime_failed"
    assert diagnostic.next_command == "ces doctor --deep --runtime codex"
    assert diagnostic.product_may_be_complete is False


def test_diagnostic_reports_no_blocker_for_approved_project() -> None:
    from ces.cli._blocker_diagnostics import diagnose_builder_report

    diagnostic = diagnose_builder_report(
        _report(
            review_state="approved",
            latest_outcome="approved",
            approval_decision="approved",
            workflow_state="approved",
            evidence_quality_state="complete",
        )
    )

    assert diagnostic.category == "none"
    assert diagnostic.reason == "No active blocker; the latest builder run is approved."
    assert diagnostic.next_command == "ces report builder"
