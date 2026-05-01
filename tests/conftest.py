"""Shared test fixtures and configuration for the CES test suite."""

from __future__ import annotations

import asyncio
import gc
import os
import sys
from collections.abc import Generator

import pytest
import pytest_asyncio.plugin as pytest_asyncio_plugin

from ces.shared.crypto import generate_keypair

# Enable the service-factory auto-provisioning path so tests that enter
# ``get_services()`` without first running ``ces init`` still work. The
# factory reads this env var and generates ephemeral key material under
# the current ``.ces/keys/`` — production CLI invocations never have this
# env var set, so real users still have to go through ``ces init``.
# Set at module import time so every test collection process inherits it,
# not only those that load the unit-suite conftest.
os.environ.setdefault("CES_PYTEST_AUTO_PROVISION_KEYS", "1")

if sys.platform == "win32":
    # Pytest-asyncio/anyio can leave the default Proactor loop's socketpair open
    # at interpreter shutdown on Windows. Use the selector policy for tests.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _get_existing_event_loop_no_warn(
    policy: asyncio.AbstractEventLoopPolicy | None = None,
) -> asyncio.AbstractEventLoop:
    """Return an already-associated loop without implicitly creating a new one."""
    target_policy = policy or asyncio.get_event_loop_policy()
    local = getattr(target_policy, "_local", None)
    loop = getattr(local, "_loop", None)
    if loop is None:
        raise RuntimeError("No current event loop")
    return loop


pytest_asyncio_plugin._get_event_loop_no_warn = _get_existing_event_loop_no_warn


@pytest.fixture(scope="session", autouse=True)
def _close_implicit_event_loop() -> Generator[None, None, None]:
    """Close any policy-managed default loop left behind by async test plugins."""
    yield

    policy = asyncio.get_event_loop_policy()
    local = getattr(policy, "_local", None)
    loop = getattr(local, "_loop", None)
    if loop is None:
        return
    if not loop.is_closed():
        loop.close()
    policy.set_event_loop(None)


def _close_orphaned_event_loops() -> None:
    for obj in gc.get_objects():
        if isinstance(obj, asyncio.BaseEventLoop) and not obj.is_closed() and not obj.is_running():
            try:
                obj.close()
            except (AttributeError, OSError, RuntimeError, ValueError):
                continue


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Close orphaned asyncio loops before pytest checks unraisable warnings."""
    del session, exitstatus
    _close_orphaned_event_loops()


@pytest.fixture()
def ed25519_keypair() -> tuple[bytes, bytes]:
    """Generate a fresh Ed25519 keypair for testing."""
    return generate_keypair()


@pytest.fixture()
def ed25519_private_key(ed25519_keypair: tuple[bytes, bytes]) -> bytes:
    """Return the private key bytes from a generated keypair."""
    return ed25519_keypair[0]


@pytest.fixture()
def ed25519_public_key(ed25519_keypair: tuple[bytes, bytes]) -> bytes:
    """Return the public key bytes from a generated keypair."""
    return ed25519_keypair[1]
