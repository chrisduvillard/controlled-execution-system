"""Control plane services.

Re-exports all service classes for convenient imports.
"""

from ces.control.services.audit_ledger import AuditLedgerService
from ces.control.services.cascade_invalidation import CascadeInvalidationEngine
from ces.control.services.classification import (
    CLASSIFICATION_TABLE,
    ClassificationEngine,
)
from ces.control.services.gate_evaluator import GateEvaluator
from ces.control.services.invalidation import InvalidationTracker
from ces.control.services.kill_switch import KillSwitchProtocol, KillSwitchService
from ces.control.services.manifest_manager import ManifestManager
from ces.control.services.merge_controller import MergeController
from ces.control.services.policy_engine import PolicyEngine
from ces.control.services.workflow_engine import TaskWorkflow, WorkflowEngine

__all__ = [
    "CLASSIFICATION_TABLE",
    "AuditLedgerService",
    "CascadeInvalidationEngine",
    "ClassificationEngine",
    "ClassificationOracle",
    "GateEvaluator",
    "InvalidationTracker",
    "KillSwitchProtocol",
    "KillSwitchService",
    "ManifestManager",
    "MergeController",
    "PolicyEngine",
    "TaskWorkflow",
    "WorkflowEngine",
]


def __getattr__(name: str) -> object:
    """Lazy import for ClassificationOracle to avoid circular import.

    ClassificationOracle depends on OracleClassificationResult which depends
    on ClassificationRule from this package. Eager import would create a cycle.
    Import directly: from ces.control.services.classification_oracle import ClassificationOracle
    """
    if name == "ClassificationOracle":
        from ces.control.services.classification_oracle import ClassificationOracle

        return ClassificationOracle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
