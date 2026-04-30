"""Service factory for CLI commands.

CES is published as a local builder-first product. ``get_services()``
therefore constructs the local SQLite-backed service graph and rejects legacy
server-mode configs with an explicit migration error.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import typer

from ces.cli._context import find_project_root, get_project_config
from ces.cli._legacy_config import reject_server_mode
from ces.cli._services import CESServices
from ces.execution.agent_runner import AgentRunner
from ces.execution.providers.bootstrap import (
    _NullLLMProvider,
)
from ces.execution.providers.bootstrap import (
    build_provider_registry as _build_provider_registry,
)
from ces.execution.providers.bootstrap import (
    register_cli_fallback as _register_cli_fallback,
)
from ces.execution.runtimes.registry import RuntimeRegistry
from ces.harness.services.self_correction_manager import SelfCorrectionManager
from ces.local_store import (
    LocalAuditRepository,
    LocalLegacyBehaviorRepository,
    LocalManifestRepository,
    LocalProjectStore,
)
from ces.shared.config import CESSettings

__all__ = [
    "_NullLLMProvider",
    "_build_provider_registry",
    "_register_cli_fallback",
    "get_services",
    "get_settings",
]


_TEST_AUTO_PROVISION_ENV = "CES_PYTEST_AUTO_PROVISION_KEYS"


def _maybe_provision_test_keys(keys_dir: Path) -> None:
    """Generate ephemeral key material inside the unit-test harness only.

    Guarded by the ``CES_PYTEST_AUTO_PROVISION_KEYS`` env var, which is set
    exclusively by ``tests/unit/conftest.py``. Production CLI invocations
    never hit this path — they require ``ces init`` to have written real
    key material.
    """
    if os.environ.get(_TEST_AUTO_PROVISION_ENV) != "1":
        return
    if (keys_dir / "ed25519_private.key").exists():
        return
    from ces.shared.crypto import (
        AUDIT_HMAC_FILENAME,
        generate_audit_hmac_secret,
        generate_keypair,
        save_audit_hmac_secret,
        save_keypair_to_dir,
    )

    keys_dir.mkdir(parents=True, exist_ok=True)
    private_key, public_key = generate_keypair()
    save_keypair_to_dir(keys_dir, private_key, public_key)
    hmac_path = keys_dir / AUDIT_HMAC_FILENAME
    if not hmac_path.exists():
        save_audit_hmac_secret(hmac_path, generate_audit_hmac_secret())


def get_settings() -> CESSettings:
    """Return a CESSettings instance from environment variables and project .env.

    Safe to call without a database connection.  Used by commands
    like ``ces init`` that only need configuration values.

    Returns:
        CESSettings populated from CES_* environment variables.
    """
    try:
        project_root = find_project_root()
    except typer.BadParameter:
        return CESSettings()
    return CESSettings(_env_file=project_root / ".env")


@asynccontextmanager
async def get_services() -> AsyncGenerator[CESServices, None]:
    """Async context manager that yields the local CES service graph."""
    from ces.brownfield.services.legacy_register import LegacyBehaviorService
    from ces.control.services.audit_ledger import AuditLedgerService
    from ces.control.services.classification import ClassificationEngine
    from ces.control.services.classification_oracle import ClassificationOracle
    from ces.control.services.gate_evaluator import GateEvaluator
    from ces.control.services.kill_switch import KillSwitchService
    from ces.control.services.manifest_manager import ManifestManager
    from ces.control.services.merge_controller import MergeController
    from ces.emergency.services.emergency_service import EmergencyService
    from ces.harness.services.evidence_synthesizer import EvidenceSynthesizer
    from ces.harness.services.guide_pack_builder import GuidePackBuilder
    from ces.harness.services.hidden_check_engine import HiddenCheckEngine
    from ces.harness.services.review_router import ReviewRouter
    from ces.harness.services.sensor_orchestrator import SensorOrchestrator
    from ces.harness.services.trust_manager import TrustManager
    from ces.intake.services.interview_engine import IntakeInterviewEngine
    from ces.knowledge.services.note_ranker import NoteRanker
    from ces.knowledge.services.vault_service import KnowledgeVaultService
    from ces.shared.crypto import (
        AUDIT_HMAC_FILENAME,
        load_audit_hmac_secret,
        load_keypair_from_dir,
    )

    settings = get_settings()
    try:
        project_root = find_project_root()
        project_config = get_project_config(project_root)
    except typer.BadParameter:
        # Not inside a CES project — let consumers (e.g. ``ces init``)
        # operate without a config rather than crash here.
        project_root = Path.cwd()
        project_config = {}

    reject_server_mode(project_config)

    # Layer 0 -- Crypto keys and local persistence.
    # The signing keypair and audit HMAC secret are written to .ces/keys/ on
    # `ces init`; we load them here so signatures produced in one CLI
    # invocation can be verified by the next one. Before 0.1.2 these were
    # regenerated per-process, which silently defeated manifest integrity.
    ces_dir = project_root / ".ces"
    keys_dir = ces_dir / "keys"
    _maybe_provision_test_keys(keys_dir)
    try:
        private_key, public_key = load_keypair_from_dir(keys_dir)
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        # ``settings.audit_hmac_secret`` is whatever pydantic-settings resolved
        # (explicit env var, .env file, or the hardcoded dev default). The
        # loader ignores the dev-default marker string and falls through to
        # the on-disk secret, so a user who forgets to override in CI still
        # gets a real project-scoped secret rather than the public placeholder.
        # If env is explicitly set to a non-default value it wins; if no file
        # and no real env are available we fail closed with a remediation hint.
        audit_secret = load_audit_hmac_secret(
            keys_dir / AUDIT_HMAC_FILENAME,
            env_override=settings.audit_hmac_secret,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc

    settings.enforce_resolved_secrets(audit_secret)

    project_id = project_config.get("project_id", "default")
    store = LocalProjectStore(
        db_path=ces_dir / "state.db",
        project_id=project_id,
    )
    store.save_project_settings(
        {
            "project_name": project_config.get("project_name"),
            "project_id": project_id,
            "execution_mode": project_config.get("execution_mode", "local"),
            "preferred_runtime": project_config.get("preferred_runtime"),
            "version": project_config.get("version"),
        }
    )

    local_audit_repo = LocalAuditRepository(store)
    local_manifest_repo = LocalManifestRepository(store)
    local_legacy_repo = LocalLegacyBehaviorRepository(store)

    # Layer 1 -- Foundation services
    audit_ledger = AuditLedgerService(
        secret_key=audit_secret,
        repository=local_audit_repo,
        project_id=project_id,
    )
    classification_engine = ClassificationEngine()
    kill_switch = KillSwitchService(audit_ledger=audit_ledger)

    # Layer 2 -- Core services
    classification_oracle = ClassificationOracle()
    manifest_manager = ManifestManager(
        private_key=private_key,
        public_key=public_key,
        audit_ledger=audit_ledger,
        classification_engine=classification_engine,
        repository=local_manifest_repo,
    )
    gate_evaluator = GateEvaluator()
    trust_manager = TrustManager(
        audit_ledger=audit_ledger,
        kill_switch=kill_switch,
    )
    sensor_orchestrator = SensorOrchestrator(
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
    )

    from ces.harness.sensors.accessibility import AccessibilitySensor
    from ces.harness.sensors.completion_gate import LintSensor, TestPassSensor, TypeCheckSensor
    from ces.harness.sensors.dependency import DependencySensor
    from ces.harness.sensors.infrastructure import InfrastructureSensor
    from ces.harness.sensors.migration import MigrationSensor
    from ces.harness.sensors.performance import PerformanceSensor
    from ces.harness.sensors.resilience import ResilienceSensor
    from ces.harness.sensors.security import SecuritySensor
    from ces.harness.sensors.test_coverage import CoverageSensor

    for sensor_cls in [
        SecuritySensor,
        PerformanceSensor,
        DependencySensor,
        InfrastructureSensor,
        ResilienceSensor,
        MigrationSensor,
        AccessibilitySensor,
        CoverageSensor,
    ]:
        sensor_orchestrator.register_sensor(sensor_cls())

    # Completion-Gate sensor registry (P1c) -- separate from the orchestrator
    # because the gate runs only the sensors a manifest opts into, not all of them.
    from ces.harness.services.completion_verifier import CompletionVerifier

    completion_sensors = {
        "test_pass": TestPassSensor(),
        "lint": LintSensor(),
        "typecheck": TypeCheckSensor(),
        "coverage": CoverageSensor(),
    }
    completion_verifier = CompletionVerifier(
        sensors=completion_sensors,
        kill_switch=kill_switch,
    )

    # Layer 3a -- LLM Provider Registry (CLI-backed or demo only)
    provider_registry, _ = _build_provider_registry(settings)

    # Layer 3b -- ReviewExecutor (needs provider_registry)
    from ces.harness.services.review_executor import LLMReviewExecutor

    review_executor = LLMReviewExecutor(
        provider_registry=provider_registry,
        kill_switch=kill_switch,
    )

    # Layer 3c -- Local integrations
    review_router = ReviewRouter(
        model_roster=settings.model_roster,
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
        review_executor=review_executor,
    )
    evidence_synthesizer = EvidenceSynthesizer(
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
    )
    hidden_check_engine = HiddenCheckEngine(pool=[])
    vault_service = KnowledgeVaultService(audit_ledger=audit_ledger)
    intake_engine = IntakeInterviewEngine(audit_ledger=audit_ledger)
    emergency_service = EmergencyService(
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
    )
    merge_controller = MergeController(
        kill_switch=kill_switch,
        gate_evaluator=gate_evaluator,
        audit_ledger=audit_ledger,
    )
    guide_pack_builder = GuidePackBuilder(
        kill_switch=kill_switch,
        audit_ledger=audit_ledger,
    )
    legacy_behavior_service = LegacyBehaviorService(
        repository=local_legacy_repo,
        audit_ledger=audit_ledger,
    )

    runtime_registry = RuntimeRegistry()
    agent_runner = AgentRunner(
        provider=None,
        kill_switch=kill_switch,
    )

    try:
        services: CESServices = {
            "settings": settings,
            "project_config": project_config,
            "local_store": store,
            "audit_ledger": audit_ledger,
            "classification_engine": classification_engine,
            "classification_oracle": classification_oracle,
            "kill_switch": kill_switch,
            "manifest_manager": manifest_manager,
            "gate_evaluator": gate_evaluator,
            "trust_manager": trust_manager,
            "sensor_orchestrator": sensor_orchestrator,
            "completion_verifier": completion_verifier,
            "self_correction_manager": SelfCorrectionManager(
                kill_switch=kill_switch,
                audit_ledger=audit_ledger,
            ),
            "review_router": review_router,
            "evidence_synthesizer": evidence_synthesizer,
            "hidden_check_engine": hidden_check_engine,
            "intake_engine": intake_engine,
            "vault_service": vault_service,
            "emergency_service": emergency_service,
            "merge_controller": merge_controller,
            "guide_pack_builder": guide_pack_builder,
            "legacy_behavior_service": legacy_behavior_service,
            "provider_registry": provider_registry,
            "runtime_registry": runtime_registry,
            "agent_runner": agent_runner,
            "note_ranker": NoteRanker,
        }
        yield services
    finally:
        store.close()
