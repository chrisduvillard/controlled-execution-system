"""Unit test conftest: ensure clean environment for config tests.

Prevents CES_ environment variable leakage from integration fixtures
into unit tests (T-10-01).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from ces.shared.crypto import (
    AUDIT_HMAC_FILENAME,
    generate_audit_hmac_secret,
    generate_keypair,
    save_audit_hmac_secret,
    save_keypair_to_dir,
)
from ces.shared.enums import (
    ArtifactStatus,
    BehaviorConfidence,
    ChangeClass,
    RiskTier,
)

CES_TEST_AUTO_PROVISION_ENV = "CES_PYTEST_AUTO_PROVISION_KEYS"


@pytest.fixture(autouse=True)
def _clean_ces_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove CES_ env vars that may leak from integration fixtures.

    Autouse ensures every unit test starts with a clean env. Uses
    monkeypatch so original env is restored after each test.

    Preserves :data:`CES_TEST_AUTO_PROVISION_ENV` so the service factory
    knows it's running in the unit-test harness and should provision
    missing ``.ces/keys/`` on demand (B1/B2 fixture parity).
    """
    for key in list(os.environ):
        if key.startswith("CES_") and key != CES_TEST_AUTO_PROVISION_ENV:
            monkeypatch.delenv(key, raising=False)
    # Opt-in marker: factory auto-provisions ephemeral keys if .ces/keys is
    # missing under the current working directory. Never set in production.
    monkeypatch.setenv(CES_TEST_AUTO_PROVISION_ENV, "1")


def _ensure_project_keys(project_root: Path) -> None:
    """Provision `.ces/keys/` under ``project_root`` if missing.

    Called by the factory when the auto-provision env var is set. Uses the
    same public save_* helpers that ``ces init`` uses, so the fixture path
    exercises the shipped write code.
    """
    keys_dir = project_root / ".ces" / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    if not (keys_dir / "ed25519_private.key").exists():
        private_key, public_key = generate_keypair()
        save_keypair_to_dir(keys_dir, private_key, public_key)
    hmac_path = keys_dir / AUDIT_HMAC_FILENAME
    if not hmac_path.exists():
        save_audit_hmac_secret(hmac_path, generate_audit_hmac_secret())


def make_sample_manifest_kwargs() -> dict[str, Any]:
    """Return a fresh dict of valid TaskManifest constructor kwargs.

    Single source of truth for the baseline TaskManifest used across unit
    tests (model tests and service-level spec-provenance tests). Returns a
    new dict on every call so callers can mutate it without cross-test
    interaction.
    """
    now = datetime.now(timezone.utc)
    return {
        "manifest_id": "MANIF-001",
        "description": "Implement user login endpoint",
        "risk_tier": RiskTier.B,
        "behavior_confidence": BehaviorConfidence.BC2,
        "change_class": ChangeClass.CLASS_2,
        "affected_files": ("src/auth/login.py",),
        "token_budget": 5000,
        "expires_at": now + timedelta(days=7),
        "version": 1,
        "status": ArtifactStatus.DRAFT,
        "owner": "system",
        "created_at": now,
        "last_confirmed": now,
    }


@pytest.fixture()
def sample_manifest_kwargs() -> dict[str, Any]:
    """Valid kwargs for directly constructing a TaskManifest.

    Yields a fresh dict each invocation so tests can mutate without
    polluting sibling tests. Consumers include:
    - tests/unit/test_models/test_manifest.py (via _make_manifest helper)
    - tests/unit/test_services/test_manifest_manager.py (spec-provenance)
    """
    return make_sample_manifest_kwargs()
