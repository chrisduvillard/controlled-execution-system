"""Cross-invocation manifest signing regression tests (B1 fix, 0.1.2).

Before 0.1.2, ``_factory.get_services`` called ``generate_keypair`` on every
invocation, so a manifest signed during one CLI command could not be verified
by any later command: the public key used for verification was fresh random
data, not the key that had produced the signature. These tests lock in the
behaviour we actually want — the key persisted to ``.ces/keys/`` by
``ces init`` is loaded on every service-factory entry, so signatures round-trip
across independent entries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ces.cli._factory import get_services
from ces.cli.init_cmd import initialize_local_project
from ces.control.models.manifest import TaskManifest
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
)


def _draft_manifest() -> TaskManifest:
    now = datetime.now(timezone.utc)
    return TaskManifest(
        manifest_id="MANIF-cross-proc",
        description="Cross-process signing probe",
        risk_tier=RiskTier.C,
        behavior_confidence=BehaviorConfidence.BC1,
        change_class=ChangeClass.CLASS_3,
        affected_files=("src/probe.py",),
        token_budget=1000,
        expires_at=now + timedelta(days=1),
        version=1,
        status=ArtifactStatus.DRAFT,
        owner="test",
        created_at=now,
        last_confirmed=now,
    )


@pytest.mark.asyncio
async def test_signature_verifies_across_factory_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A manifest signed under one get_services context must verify under the next."""
    monkeypatch.chdir(tmp_path)
    # Real init path — writes the persistent keypair + HMAC secret.
    initialize_local_project(tmp_path, name="crossproc")
    # Prevent the unit-test auto-provision fallback from masking the real load.
    monkeypatch.delenv("CES_PYTEST_AUTO_PROVISION_KEYS", raising=False)

    async with get_services() as services_a:
        manager_a = services_a["manifest_manager"]
        signed = await manager_a.sign_manifest(_draft_manifest())
        signature = signed.signature
        assert signature, "signing did not produce a signature"

    # Exit context and re-enter — simulates a second CLI invocation.
    async with get_services() as services_b:
        manager_b = services_a["manifest_manager"]
        assert await manager_b.verify_manifest(signed) is True, (
            "Signature produced in the first factory entry must verify in the "
            "second — if this fails, the keypair is no longer persistent."
        )


@pytest.mark.asyncio
async def test_tampered_manifest_fails_verification_cross_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once a manifest is signed, altering its content must fail verification."""
    monkeypatch.chdir(tmp_path)
    initialize_local_project(tmp_path, name="crossproctamper")
    monkeypatch.delenv("CES_PYTEST_AUTO_PROVISION_KEYS", raising=False)

    async with get_services() as services_a:
        manager_a = services_a["manifest_manager"]
        signed = await manager_a.sign_manifest(_draft_manifest())

    tampered = signed.model_copy(update={"description": "TAMPERED"})
    async with get_services() as services_b:
        manager_b = services_a["manifest_manager"]
        assert await manager_b.verify_manifest(tampered) is False
