"""Typed service container for CES CLI commands.

Replaces the historical untyped ``dict[str, Any]`` with a ``TypedDict`` so the
type checker can verify keys and yielded values. The runtime representation is
still a plain ``dict``, so existing test fixtures that build partial mock
dictionaries and mutate them via item assignment continue to work unchanged.

Production code accesses fields via dict syntax (``services["manifest_manager"]``).
``mypy`` then narrows the value type to the declared field, replacing the
former ``Any``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from ces.brownfield.services.legacy_register import LegacyBehaviorService
    from ces.control.services.audit_ledger import AuditLedgerService
    from ces.control.services.classification import ClassificationEngine
    from ces.control.services.classification_oracle import ClassificationOracle
    from ces.control.services.gate_evaluator import GateEvaluator
    from ces.control.services.kill_switch import KillSwitchService
    from ces.control.services.manifest_manager import ManifestManager
    from ces.control.services.merge_controller import MergeController
    from ces.emergency.services.emergency_service import EmergencyService
    from ces.execution.agent_runner import AgentRunner
    from ces.execution.providers.registry import ProviderRegistry
    from ces.execution.runtimes.registry import RuntimeRegistry
    from ces.harness.services.completion_verifier import CompletionVerifier
    from ces.harness.services.evidence_synthesizer import EvidenceSynthesizer
    from ces.harness.services.guide_pack_builder import GuidePackBuilder
    from ces.harness.services.hidden_check_engine import HiddenCheckEngine
    from ces.harness.services.review_router import ReviewRouter
    from ces.harness.services.self_correction_manager import SelfCorrectionManager
    from ces.harness.services.sensor_orchestrator import SensorOrchestrator
    from ces.harness.services.trust_manager import TrustManager
    from ces.intake.services.interview_engine import IntakeInterviewEngine
    from ces.knowledge.services.note_ranker import NoteRanker
    from ces.knowledge.services.vault_service import KnowledgeVaultService
    from ces.local_store import LocalProjectStore
    from ces.shared.config import CESSettings


class CESServices(TypedDict, total=False):
    """Resolved service graph yielded by ``ces.cli._factory.get_services``.

    ``total=False`` makes every key optional from a static-checking standpoint:
    test fixtures can provide partial mocks, and production code that expects a
    field to be present accesses it as ``services["X"]`` (raising ``KeyError``
    if absent — a real bug rather than a silent ``None``).
    """

    settings: CESSettings
    project_config: dict[str, Any]
    local_store: LocalProjectStore

    audit_ledger: AuditLedgerService
    classification_engine: ClassificationEngine
    classification_oracle: ClassificationOracle
    kill_switch: KillSwitchService

    manifest_manager: ManifestManager
    gate_evaluator: GateEvaluator
    trust_manager: TrustManager
    sensor_orchestrator: SensorOrchestrator
    completion_verifier: CompletionVerifier
    self_correction_manager: SelfCorrectionManager

    review_router: ReviewRouter
    evidence_synthesizer: EvidenceSynthesizer
    hidden_check_engine: HiddenCheckEngine
    intake_engine: IntakeInterviewEngine
    vault_service: KnowledgeVaultService
    emergency_service: EmergencyService
    merge_controller: MergeController
    guide_pack_builder: GuidePackBuilder
    legacy_behavior_service: LegacyBehaviorService

    provider_registry: ProviderRegistry
    runtime_registry: RuntimeRegistry
    agent_runner: AgentRunner

    note_ranker: type[NoteRanker]
