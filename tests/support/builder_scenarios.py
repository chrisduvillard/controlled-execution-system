"""Reusable builder-loop scenario harnesses and fixtures."""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copytree
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from ces.local_store import LocalProjectStore
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    LegacyDisposition,
    RiskTier,
    WorkflowState,
)

runner = CliRunner()
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "builder_scenarios"


def _completion_stdout(*, criterion: str) -> str:
    return (
        "Done\n"
        "```ces:completion\n"
        "{"
        '"task_id": "M-001", '
        '"summary": "did it", '
        '"files_changed": [], '
        f'"criteria_satisfied": [{{"criterion": "{criterion}", "evidence": "scenario evidence", '
        '"evidence_kind": "manual_inspection"}], '
        '"open_questions": [], '
        '"scope_deviations": []'
        "}\n"
        "```"
    )


@dataclass(frozen=True)
class _FakeManifest:
    manifest_id: str
    description: str
    risk_tier: RiskTier
    behavior_confidence: BehaviorConfidence
    change_class: ChangeClass
    affected_files: list[str]
    token_budget: int
    status: ArtifactStatus = ArtifactStatus.DRAFT
    workflow_state: WorkflowState = WorkflowState.IN_FLIGHT
    created_at: datetime = datetime.now(timezone.utc)
    expires_at: datetime = datetime.now(timezone.utc) + timedelta(hours=1)
    content_hash: str | None = None

    def model_copy(self, update: dict[str, Any]):
        return replace(self, **update)

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "description": self.description,
            "risk_tier": self.risk_tier.value,
            "behavior_confidence": self.behavior_confidence.value,
            "change_class": self.change_class.value,
            "affected_files": self.affected_files,
            "token_budget": self.token_budget,
            "status": self.status.value,
            "workflow_state": self.workflow_state.value,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(frozen=True)
class BuilderScenario:
    name: str
    request: str
    fixture_name: str | None
    build_args: tuple[str, ...]
    prompt_responses: tuple[str, ...]
    proposal: dict[str, Any]
    execution_results: tuple[dict[str, Any], ...]
    brownfield_review: bool = False


@dataclass(frozen=True)
class BuilderScenarioResult:
    scenario_name: str
    project_root: Path
    build: Any
    explain: Any
    status: Any
    continue_: Any
    latest_snapshot: Any | None = None
    final_explain: Any | None = None
    final_status: Any | None = None
    runtime_retry_preserved_review_count: bool = False


def materialize_builder_fixture(name: str, target: Path) -> None:
    source = _FIXTURE_ROOT / name
    if not source.is_dir():
        raise FileNotFoundError(f"Unknown builder fixture: {name}")
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            copytree(item, destination)
        else:
            destination.write_bytes(item.read_bytes())


GREENFIELD_SCENARIO = BuilderScenario(
    name="greenfield-habit-tracker",
    request="Build a habit tracker",
    fixture_name=None,
    build_args=(
        "build",
        "Build a habit tracker",
        "--yes",
        "--accept-runtime-side-effects",
        "--acceptance",
        "Users can create and complete habits",
    ),
    prompt_responses=(
        "Expose an HTTP endpoint",
        "Users can create and complete habits",
        "Existing CLI commands",
    ),
    proposal={
        "description": "Build a habit tracker",
        "risk_tier": RiskTier.C.value,
        "behavior_confidence": BehaviorConfidence.BC1.value,
        "change_class": ChangeClass.CLASS_1.value,
        "affected_files": ["app.py"],
        "token_budget": 50000,
        "reasoning": "Low-risk greenfield request",
    },
    execution_results=(
        {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": "gpt-5.4",
            "invocation_ref": "run-greenfield-1",
            "exit_code": 0,
            "stdout": _completion_stdout(criterion="Users can create and complete habits"),
            "stderr": "",
            "duration_seconds": 0.5,
        },
    ),
)


BROWNFIELD_RETRY_SCENARIO = BuilderScenario(
    name="brownfield-billing-retry",
    request="Modernize billing exports",
    fixture_name="brownfield-billing",
    build_args=(
        "build",
        "Modernize billing exports",
        "--yes",
        "--accept-runtime-side-effects",
        "--acceptance",
        "Admins can still export billing rows",
        "--source-of-truth",
        "README and exported CSV samples",
        "--critical-flow",
        "Billing export",
    ),
    prompt_responses=(
        "Keep the existing CSV export intact",
        "Admins can still export billing rows",
        "CSV export format",
        "README and exported CSV samples",
        "Billing export",
        "preserve",
        "",
        "preserve",
        "change",
        "under_investigation",
        "preserve",
        "",
        "preserve",
        "",
    ),
    proposal={
        "description": "Modernize billing exports",
        "risk_tier": RiskTier.B.value,
        "behavior_confidence": BehaviorConfidence.BC2.value,
        "change_class": ChangeClass.CLASS_2.value,
        "affected_files": ["billing_export.py"],
        "token_budget": 75000,
        "reasoning": "Brownfield change in an existing codebase",
    },
    execution_results=(
        {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": "gpt-5.4",
            "invocation_ref": "run-brownfield-1",
            "exit_code": 1,
            "stdout": "",
            "stderr": "boom",
            "duration_seconds": 0.5,
        },
        {
            "runtime_name": "codex",
            "runtime_version": "1.0.0",
            "reported_model": "gpt-5.4",
            "invocation_ref": "run-brownfield-2",
            "exit_code": 0,
            "stdout": _completion_stdout(criterion="Admins can still export billing rows"),
            "stderr": "",
            "duration_seconds": 0.5,
        },
    ),
    brownfield_review=True,
)


class BuilderScenarioHarness:
    """Materialize realistic repo fixtures and run deterministic builder-loop scenarios."""

    def __init__(self, *, tmp_path: Path, monkeypatch: Any) -> None:
        self._tmp_path = tmp_path
        self._monkeypatch = monkeypatch

    def run(self, scenario: BuilderScenario) -> BuilderScenarioResult:
        self._tmp_path.mkdir(parents=True, exist_ok=True)
        if scenario.fixture_name:
            materialize_builder_fixture(scenario.fixture_name, self._tmp_path)

        self._monkeypatch.chdir(self._tmp_path)
        store = _prepare_local_project(self._tmp_path)
        prompt_values = iter(scenario.prompt_responses)
        self._monkeypatch.setattr(
            "ces.cli.run_cmd.typer.prompt",
            lambda *args, **kwargs: next(prompt_values),
        )

        legacy_behavior_service = _make_brownfield_legacy_service() if scenario.brownfield_review else None
        services = _make_services(
            store,
            proposal=scenario.proposal,
            execution_results=list(scenario.execution_results),
            legacy_behavior_service=legacy_behavior_service,
        )

        with _patch_builder_cli_services(services):
            app = _get_app()
            build = runner.invoke(app, list(scenario.build_args))
            explain = runner.invoke(app, ["explain"])
            status = runner.invoke(app, ["status"])

            retry_preserved_review_count = False
            final_explain = None
            final_status = None

            if scenario.brownfield_review and legacy_behavior_service is not None:
                review_count = legacy_behavior_service.register_behavior.await_count
                self._monkeypatch.setattr(
                    "ces.cli.run_cmd.typer.prompt",
                    lambda *args, **kwargs: (_ for _ in ()).throw(
                        AssertionError("brownfield review should not rerun during runtime retry")
                    ),
                )
                continue_result = runner.invoke(app, ["continue", "--yes", "--accept-runtime-side-effects"])
                retry_preserved_review_count = legacy_behavior_service.register_behavior.await_count == review_count
                final_explain = runner.invoke(app, ["explain"])
                final_status = runner.invoke(app, ["status"])
            else:
                continue_result = runner.invoke(app, ["continue", "--yes", "--accept-runtime-side-effects"])

            latest_snapshot = store.get_latest_builder_session_snapshot()

            return BuilderScenarioResult(
                scenario_name=scenario.name,
                project_root=self._tmp_path,
                build=build,
                explain=explain,
                status=status,
                continue_=continue_result,
                latest_snapshot=latest_snapshot,
                final_explain=final_explain,
                final_status=final_status,
                runtime_retry_preserved_review_count=retry_preserved_review_count,
            )


def _get_app():
    from ces.cli import app

    return app


def _prepare_local_project(tmp_path: Path) -> LocalProjectStore:
    ces_dir = tmp_path / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text(
        "project_id: local-proj\npreferred_runtime: codex\n",
        encoding="utf-8",
    )
    return LocalProjectStore(ces_dir / "state.db", project_id="local-proj")


def _patch_builder_cli_services(mock_services: dict[str, Any]):
    @asynccontextmanager
    async def _fake_get_services(*args: Any, **kwargs: Any):
        del args, kwargs
        yield mock_services

    stack = ExitStack()
    stack.enter_context(patch("ces.cli.run_cmd.get_services", new=_fake_get_services))
    stack.enter_context(patch("ces.cli.status_cmd.get_services", new=_fake_get_services))
    return stack


def _make_services(
    store: LocalProjectStore,
    *,
    proposal: dict[str, Any],
    execution_results: list[dict[str, Any]],
    legacy_behavior_service: Any | None = None,
) -> dict[str, Any]:
    manifest_counter = {"value": 0}

    async def _create_manifest(**kwargs):
        manifest_counter["value"] += 1
        return _FakeManifest(
            manifest_id=f"M-{manifest_counter['value']:03d}",
            description=kwargs["description"],
            risk_tier=kwargs["risk_tier"],
            behavior_confidence=kwargs["behavior_confidence"],
            change_class=kwargs["change_class"],
            affected_files=list(kwargs["affected_files"]),
            token_budget=kwargs["token_budget"],
        )

    async def _save_manifest(manifest):
        store.save_manifest(manifest)

    async def _get_active_manifests():
        return store.get_active_manifest_rows()

    runtime = MagicMock()
    runtime.runtime_name = "codex"
    runtime.generate_manifest_assist.return_value = proposal

    runner_service = AsyncMock()
    runner_service.execute_runtime = AsyncMock(side_effect=execution_results)

    synth = MagicMock()
    synth.format_summary_slots = AsyncMock(
        return_value=SimpleNamespace(
            summary="Execution summary is available.",
            challenge="Review the latest evidence carefully.",
        )
    )
    synth.triage = AsyncMock(
        return_value=SimpleNamespace(
            color=SimpleNamespace(value="yellow"),
            auto_approve_eligible=False,
            reason="Evidence requires review.",
        )
    )

    manifest_manager = AsyncMock()
    manifest_manager.create_manifest = AsyncMock(side_effect=_create_manifest)
    manifest_manager.save_manifest = AsyncMock(side_effect=_save_manifest)
    manifest_manager.get_active_manifests = AsyncMock(side_effect=_get_active_manifests)

    audit_ledger = AsyncMock()
    audit_ledger.record_approval = AsyncMock()
    audit_ledger.query_by_time_range = AsyncMock(return_value=[])

    return {
        "settings": MagicMock(default_runtime="codex"),
        "manifest_manager": manifest_manager,
        "runtime_registry": MagicMock(
            resolve_runtime=MagicMock(return_value=runtime),
        ),
        "agent_runner": runner_service,
        "local_store": store,
        "evidence_synthesizer": synth,
        "audit_ledger": audit_ledger,
        "sensor_orchestrator": MagicMock(run_all=AsyncMock(return_value=[])),
        "legacy_behavior_service": legacy_behavior_service
        or AsyncMock(get_pending_behaviors=AsyncMock(return_value=[])),
        "trust_manager": AsyncMock(),
    }


def _make_brownfield_legacy_service() -> Any:
    entry_counter = {"value": 0}

    async def _register_behavior(**kwargs):
        entry_counter["value"] += 1
        return SimpleNamespace(
            entry_id=f"OLB-{entry_counter['value']}",
            behavior_description=kwargs["behavior_description"],
        )

    async def _review_behavior(entry_id: str, disposition: Any, reviewed_by: str):
        return SimpleNamespace(
            entry_id=entry_id,
            disposition=getattr(disposition, "value", disposition),
            reviewed_by=reviewed_by,
        )

    legacy_behavior_service = AsyncMock()
    legacy_behavior_service.get_pending_behaviors = AsyncMock(return_value=[])
    legacy_behavior_service.register_behavior = AsyncMock(side_effect=_register_behavior)
    legacy_behavior_service.review_behavior = AsyncMock(side_effect=_review_behavior)
    return legacy_behavior_service
