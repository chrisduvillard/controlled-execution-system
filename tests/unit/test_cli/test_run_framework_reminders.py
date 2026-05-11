"""Tests for `ces build` framework reminder prompt injection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ces.harness.models.sensor_result import SensorFinding, SensorResult
from ces.harness.services.framework_reminders import FrameworkReminder, FrameworkReminderBuilder


def _risk_sensor_result() -> SensorResult:
    return SensorResult(
        sensor_id="execution_risk_monitor",
        sensor_pack="harness_evolution",
        passed=False,
        score=0.0,
        details="risk found",
        timestamp=datetime.now(timezone.utc),
        findings=(
            SensorFinding(
                category="destructive_after_success",
                severity="critical",
                location="rm -rf dist",
                message="destructive cleanup after success",
                suggestion="rerun validation",
            ),
        ),
    )


def test_prompt_pack_injects_framework_reminders_with_evidence_reason() -> None:
    from ces.cli._builder_flow import BuilderBriefDraft
    from ces.cli.run_cmd import _prompt_pack

    reminder = FrameworkReminder(
        reminder_id="frm-abc123",
        source_sensor_id="execution_risk_monitor",
        source_category="destructive_after_success",
        severity="critical",
        content="Framework Reminder: Stop after green verification and re-run validation after destructive cleanup.",
        evidence_reason="critical finding from execution_risk_monitor: destructive_after_success",
        content_hash="0" * 64,
    )

    prompt = _prompt_pack(
        BuilderBriefDraft(
            request="Add checkout discounts",
            project_mode="greenfield",
            constraints=[],
            acceptance_criteria=["Discounts apply at checkout"],
            must_not_break=[],
            open_questions={},
            source_of_truth=None,
            critical_flows=[],
        ),
        framework_reminders=[reminder],
    )

    assert "Framework Reminders:" in prompt
    assert "frm-abc123" in prompt
    assert "Stop after green verification" in prompt
    assert "critical finding from execution_risk_monitor" in prompt
    assert "ces:completion" in prompt


def test_prompt_pack_omits_framework_reminder_section_when_empty() -> None:
    from ces.cli._builder_flow import BuilderBriefDraft
    from ces.cli.run_cmd import _prompt_pack

    prompt = _prompt_pack(
        BuilderBriefDraft(
            request="Add checkout discounts",
            project_mode="greenfield",
            constraints=[],
            acceptance_criteria=[],
            must_not_break=[],
            open_questions={},
            source_of_truth=None,
            critical_flows=[],
        ),
        framework_reminders=[],
    )

    assert "Framework Reminders:" not in prompt


def test_active_framework_reminders_builds_from_active_sensor_results() -> None:
    from ces.cli.run_cmd import _active_framework_reminders

    sensor_result = _risk_sensor_result()

    reminders = _active_framework_reminders(
        {
            "framework_reminder_builder": FrameworkReminderBuilder(),
            "active_sensor_results": [sensor_result],
        }
    )

    assert len(reminders) == 1
    assert reminders[0].source_sensor_id == "execution_risk_monitor"
    assert reminders[0].source_category == "destructive_after_success"


def test_active_framework_reminders_loads_prior_evidence_packet() -> None:
    from types import SimpleNamespace

    from ces.cli.run_cmd import _active_framework_reminders

    sensor_result = _risk_sensor_result()
    local_store = SimpleNamespace(
        get_latest_builder_session=lambda: SimpleNamespace(evidence_packet_id="EP-prev"),
        get_evidence_by_packet_id=lambda packet_id: (
            {"sensors": [sensor_result.model_dump()]} if packet_id == "EP-prev" else None
        ),
    )

    reminders = _active_framework_reminders(
        {
            "framework_reminder_builder": FrameworkReminderBuilder(),
            "local_store": local_store,
        }
    )

    assert len(reminders) == 1
    assert reminders[0].evidence_reason == "critical finding from execution_risk_monitor: destructive_after_success"


def test_active_framework_reminders_loads_latest_evidence_when_current_session_is_empty(tmp_path: Path) -> None:
    from ces.cli.run_cmd import _active_framework_reminders
    from ces.local_store import LocalProjectStore

    store = LocalProjectStore(db_path=tmp_path / "state.db", project_id="local-proj")
    try:
        store.save_builder_session(
            brief_id="BB-prev",
            request="previous run",
            project_mode="greenfield",
            stage="awaiting_review",
            next_action="review_evidence",
            last_action="evidence_ready",
            evidence_packet_id="EP-prev",
        )
        store.save_evidence(
            "M-prev",
            packet_id="EP-prev",
            summary="summary",
            challenge="challenge",
            triage_color="yellow",
            content={"sensors": [_risk_sensor_result().model_dump()]},
        )
        store.save_builder_session(
            brief_id="BB-current",
            request="new run",
            project_mode="greenfield",
            stage="manifest_draft",
            next_action="execute_runtime",
            last_action="session_started",
        )

        reminders = _active_framework_reminders(
            {
                "framework_reminder_builder": FrameworkReminderBuilder(),
                "local_store": store,
            }
        )
    finally:
        store.close()

    assert len(reminders) == 1
    assert reminders[0].source_category == "destructive_after_success"


def test_active_framework_reminders_skips_corrupt_prior_evidence_packet() -> None:
    from types import SimpleNamespace

    from ces.cli.run_cmd import _active_framework_reminders

    def corrupt_packet(_packet_id: str) -> dict[str, object]:
        raise ValueError("corrupt evidence JSON")

    local_store = SimpleNamespace(
        get_latest_builder_session=lambda: SimpleNamespace(evidence_packet_id="EP-corrupt"),
        get_evidence_by_packet_id=corrupt_packet,
        get_latest_evidence_packet=lambda: None,
    )

    reminders = _active_framework_reminders(
        {
            "framework_reminder_builder": FrameworkReminderBuilder(),
            "local_store": local_store,
        }
    )

    assert reminders == []


def test_active_framework_reminders_skips_corrupt_latest_evidence_packet() -> None:
    from types import SimpleNamespace

    from ces.cli.run_cmd import _active_framework_reminders

    def corrupt_latest_packet() -> dict[str, object]:
        raise ValueError("corrupt latest evidence JSON")

    local_store = SimpleNamespace(
        get_latest_builder_session=lambda: None,
        get_latest_evidence_packet=corrupt_latest_packet,
    )

    reminders = _active_framework_reminders(
        {
            "framework_reminder_builder": FrameworkReminderBuilder(),
            "local_store": local_store,
        }
    )

    assert reminders == []
