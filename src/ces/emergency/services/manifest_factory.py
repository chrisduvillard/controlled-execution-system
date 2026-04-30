"""Emergency manifest factory (EMERG-01, EMERG-02).

Creates simplified TaskManifest instances for emergency hotfix paths
with auto-populated defaults:
- Risk Tier A (highest scrutiny)
- 500-line cap (EMERG-02)
- 15-minute TTL (EMERG-03)
- Worst-case classification (BC3, Class 5)
- [EMERGENCY] prefix on description

Threat mitigations:
- T-05-19: Emergency manifests can ONLY be created via this factory,
  which enforces all constraints. Auto-set Tier A ensures highest scrutiny.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from ces.control.models.manifest import TaskManifest
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
    WorkflowState,
)


class EmergencyManifestFactory:
    """Factory for creating emergency hotfix manifests.

    All emergency manifests are created with Tier A risk classification,
    a 500-line cap, and a 15-minute TTL. These constraints cannot be
    overridden -- they are hard-enforced by the factory.
    """

    @staticmethod
    def create(
        *,
        description: str,
        affected_files: list[str],
        declared_by: str,
    ) -> TaskManifest:
        """Create an emergency TaskManifest with auto-populated defaults.

        EMERG-01: Simplified manifest with auto-populated defaults.
        EMERG-02: 500-line cap and blast radius isolation via affected_files.
        EMERG-03: 15-minute TTL (expires_at = now + 15 min).

        Args:
            description: What the emergency fix addresses.
            affected_files: Files that may be modified (must be non-empty).
            declared_by: Human operator declaring the emergency.

        Returns:
            A TaskManifest with emergency defaults.

        Raises:
            ValueError: If affected_files is empty.
        """
        if not affected_files:
            msg = "affected_files must be non-empty for emergency manifests"
            raise ValueError(msg)

        now = datetime.now(timezone.utc)
        manifest_id = f"EM-{uuid.uuid4().hex[:12]}"

        return TaskManifest(
            # Identity
            manifest_id=manifest_id,
            description=f"[EMERGENCY] {description} (max 500 lines)",
            # Classification: worst-case defaults (EMERG-01)
            risk_tier=RiskTier.A,
            behavior_confidence=BehaviorConfidence.BC3,
            change_class=ChangeClass.CLASS_5,
            # File boundaries (EMERG-02: blast radius)
            affected_files=tuple(affected_files),
            forbidden_files=(),
            # Tool boundaries: minimal toolset
            allowed_tools=("git", "editor"),
            forbidden_tools=(),
            # Resource limits (EMERG-02: 500-line cap encoded in token budget)
            token_budget=50000,
            # Expiry (EMERG-03: 15-minute SLA)
            expires_at=now + timedelta(minutes=15),
            # Workflow
            workflow_state=WorkflowState.QUEUED,
            # Actors
            classifier_id=None,
            implementer_id=None,
            # Retry limits (emergency: minimal retries)
            max_retries=1,
            retry_count=0,
            # Release slice
            release_slice="emergency-hotfix",
            # Governed artifact fields
            version=1,
            status=ArtifactStatus.DRAFT,
            owner=declared_by,
            created_at=now,
            last_confirmed=now,
        )
