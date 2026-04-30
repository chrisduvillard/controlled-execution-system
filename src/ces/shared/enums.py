"""Shared enumerations used across all CES planes.

All enums use (str, Enum) base for JSON serialization compatibility.
Orderable enums (RiskTier, BehaviorConfidence, ChangeClass) implement
__lt__ for aggregate classification using max().
"""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Orderable enums — support max() for aggregate classification (CLASS-02)
#
# Note: We must explicitly define __lt__, __le__, __gt__, __ge__ because
# (str, Enum) inherits str's comparison operators, which @total_ordering
# cannot override (it only fills in *missing* methods).
# ---------------------------------------------------------------------------


# Ordering maps for orderable enums (kept outside the enum class to avoid
# becoming enum members). Higher values = higher risk.
_RISK_TIER_ORDER: dict[str, int] = {"A": 3, "B": 2, "C": 1}
_BEHAVIOR_CONFIDENCE_ORDER: dict[str, int] = {"BC1": 1, "BC2": 2, "BC3": 3}
_CHANGE_CLASS_ORDER: dict[str, int] = {
    "Class 1": 1,
    "Class 2": 2,
    "Class 3": 3,
    "Class 4": 4,
    "Class 5": 5,
}


class _OrderableEnumMixin:
    """Mixin that provides risk-based ordering for str Enums.

    Subclasses must implement _ordering_value() returning an int weight.
    We explicitly define all four comparison operators because (str, Enum)
    inherits str's operators, and @total_ordering only fills in *missing* ones.
    """

    def _ordering_value(self) -> int:
        raise NotImplementedError

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._ordering_value() < other._ordering_value()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._ordering_value() <= other._ordering_value()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._ordering_value() > other._ordering_value()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._ordering_value() >= other._ordering_value()


class RiskTier(_OrderableEnumMixin, str, Enum):
    """Risk tier classification. A = highest risk, C = lowest."""

    A = "A"
    B = "B"
    C = "C"

    def _ordering_value(self) -> int:
        return _RISK_TIER_ORDER[self.value]


class BehaviorConfidence(_OrderableEnumMixin, str, Enum):
    """Behavior confidence level. BC3 = lowest confidence = highest risk."""

    BC1 = "BC1"
    BC2 = "BC2"
    BC3 = "BC3"

    def _ordering_value(self) -> int:
        return _BEHAVIOR_CONFIDENCE_ORDER[self.value]


class ChangeClass(_OrderableEnumMixin, str, Enum):
    """Change classification. CLASS_5 = highest risk."""

    CLASS_1 = "Class 1"
    CLASS_2 = "Class 2"
    CLASS_3 = "Class 3"
    CLASS_4 = "Class 4"
    CLASS_5 = "Class 5"

    def _ordering_value(self) -> int:
        return _CHANGE_CLASS_ORDER[self.value]


# ---------------------------------------------------------------------------
# Artifact lifecycle
# ---------------------------------------------------------------------------


class ArtifactStatus(str, Enum):
    """Truth artifact lifecycle status."""

    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    DEFERRED = "deferred"
    RETIRED = "retired"
    DEPRECATED = "deprecated"


class TrustStatus(str, Enum):
    """Harness profile trust level."""

    CANDIDATE = "candidate"
    TRUSTED = "trusted"
    WATCH = "watch"
    CONSTRAINED = "constrained"


# ---------------------------------------------------------------------------
# Audit ledger events (PRD SS2.9)
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Governance event types for the audit ledger."""

    APPROVAL = "approval"
    MERGE = "merge"
    INVALIDATION = "invalidation"
    EXCEPTION = "exception"
    OVERRIDE = "override"
    DEPLOYMENT = "deployment"
    ROLLBACK = "rollback"
    HARNESS_CHANGE = "harness_change"
    TRUTH_CHANGE = "truth_change"
    CLASSIFICATION = "classification"
    ESCALATION = "escalation"
    KILL_SWITCH = "kill_switch"
    RECOVERY = "recovery"
    DELEGATION = "delegation"
    CALIBRATION = "calibration"
    STATE_TRANSITION = "state_transition"
    SENSOR_RUN = "sensor_run"
    SPEC_AUTHORED = "spec_authored"
    SPEC_IMPORTED = "spec_imported"
    SPEC_DECOMPOSED = "spec_decomposed"
    SPEC_RECONCILED = "spec_reconciled"


class ActorType(str, Enum):
    """Actor type for governance event attribution."""

    HUMAN = "human"
    AGENT = "agent"
    CONTROL_PLANE = "control_plane"


# ---------------------------------------------------------------------------
# Gate types
# ---------------------------------------------------------------------------


class GateType(str, Enum):
    """Review gate assignment type."""

    AGENT = "agent"
    HYBRID = "hybrid"
    HUMAN = "human"


class GateDecision(str, Enum):
    """Gate evaluation outcome."""

    PASS = "pass"
    FAIL = "fail"
    ESCALATE = "escalate"


# ---------------------------------------------------------------------------
# PRL and prioritization
# ---------------------------------------------------------------------------


class PRLItemType(str, Enum):
    """PRL (Prioritized Requirements List) item classification."""

    FEATURE = "feature"
    CONSTRAINT = "constraint"
    QUALITY = "quality"
    INTEGRATION = "integration"
    MIGRATION = "migration"
    OPERATIONAL = "operational"


class Priority(str, Enum):
    """Priority levels for requirements and tasks."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Interface and contract types
# ---------------------------------------------------------------------------


class InterfaceType(str, Enum):
    """Types of system interfaces."""

    API = "api"
    EVENT = "event"
    SHARED_STATE = "shared_state"
    FILE = "file"
    MESSAGE_QUEUE = "message_queue"


class VersioningRule(str, Enum):
    """Versioning strategy for contracts."""

    SEMVER = "semver"
    DATED = "dated"
    HASH = "hash"


class CompatibilityRule(str, Enum):
    """Backward compatibility rules for contracts."""

    BACKWARDS_COMPATIBLE = "backwards_compatible"
    BREAKING_ALLOWED_WITH_MIGRATION = "breaking_allowed_with_migration"


class ContractStatus(str, Enum):
    """Interface contract lifecycle status."""

    DRAFT = "draft"
    APPROVED = "approved"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# ---------------------------------------------------------------------------
# Impact and sensitivity
# ---------------------------------------------------------------------------


class ImpactScope(str, Enum):
    """Scope of change impact."""

    INTERNAL = "internal"
    CROSS_TEAM = "cross_team"
    EXTERNAL = "external"


class Sensitivity(str, Enum):
    """Data sensitivity classification."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    REGULATED = "regulated"


# ---------------------------------------------------------------------------
# Technical debt
# ---------------------------------------------------------------------------


class DebtOriginType(str, Enum):
    """How technical debt was introduced."""

    INHERITED = "inherited"
    INTRODUCED = "introduced"
    DISCOVERED = "discovered"


class DebtSeverity(str, Enum):
    """Impact severity of technical debt."""

    BLOCKS_FUTURE_WORK = "blocks_future_work"
    DEGRADES_FUTURE_WORK = "degrades_future_work"
    COSMETIC = "cosmetic"


class DebtStatus(str, Enum):
    """Technical debt resolution status."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ACCEPTED_PERMANENT = "accepted_permanent"


# ---------------------------------------------------------------------------
# Legacy and disposition
# ---------------------------------------------------------------------------


class Disposition(str, Enum):
    """Disposition for existing behaviors."""

    PRESERVE = "preserve"
    CHANGE = "change"
    RETIRE = "retire"
    UNDER_INVESTIGATION = "under_investigation"


class LegacyDisposition(str, Enum):
    """Disposition for legacy behavior entries (includes NEW)."""

    PRESERVE = "preserve"
    CHANGE = "change"
    RETIRE = "retire"
    UNDER_INVESTIGATION = "under_investigation"
    NEW = "new"


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class MigrationStatus(str, Enum):
    """Migration control pack lifecycle status."""

    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Reconciliation and assumptions
# ---------------------------------------------------------------------------


class ReconciliationFrequency(str, Enum):
    """How often truth artifacts are reconciled."""

    CONTINUOUS = "continuous"
    DAILY = "daily"
    PER_RELEASE = "per_release"


class AssumptionCategory(str, Enum):
    """Assumption handling category during intake."""

    BLOCK = "block"
    FLAG = "flag"
    PROCEED = "proceed"


# ---------------------------------------------------------------------------
# Knowledge vault
# ---------------------------------------------------------------------------


class VaultTrustLevel(str, Enum):
    """Trust level for knowledge vault notes."""

    VERIFIED = "verified"
    AGENT_INFERRED = "agent-inferred"
    STALE_RISK = "stale-risk"


class VaultCategory(str, Enum):
    """Category for knowledge vault notes."""

    DECISIONS = "decisions"
    PATTERNS = "patterns"
    ESCAPES = "escapes"
    DISCOVERY = "discovery"
    CALIBRATION = "calibration"
    HARNESS = "harness"
    DOMAIN = "domain"
    STAKEHOLDERS = "stakeholders"
    SESSIONS = "sessions"


# ---------------------------------------------------------------------------
# Invalidation and rollback
# ---------------------------------------------------------------------------


class InvalidationSeverity(str, Enum):
    """Severity of truth artifact invalidation."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RollbackReadiness(str, Enum):
    """Rollback readiness status for migrations."""

    READY = "ready"
    CONDITIONAL = "conditional"
    NOT_READY = "not_ready"


# ---------------------------------------------------------------------------
# Workflow state machine
# ---------------------------------------------------------------------------


class WorkflowState(str, Enum):
    """Main workflow state machine states."""

    QUEUED = "queued"
    IN_FLIGHT = "in_flight"
    VERIFYING = "verifying"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    MERGED = "merged"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReviewSubState(str, Enum):
    """Sub-states for the review sub-workflow."""

    PENDING_REVIEW = "pending_review"
    CHALLENGER_BRIEF = "challenger_brief"
    TRIAGE = "triage"
    DECISION = "decision"


# ---------------------------------------------------------------------------
# NFR and verification
# ---------------------------------------------------------------------------


class NFRCategory(str, Enum):
    """Non-functional requirement category."""

    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    SECURITY = "security"
    SCALABILITY = "scalability"
    OBSERVABILITY = "observability"


class VerificationMethod(str, Enum):
    """How a control or requirement is verified."""

    DETERMINISTIC = "deterministic"
    INFERENTIAL = "inferential"
    MANUAL = "manual"
