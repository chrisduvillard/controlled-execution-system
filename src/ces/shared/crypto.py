"""Cryptographic utilities for CES manifest signing, content hashing, and audit chain integrity.

Uses the `cryptography` library for Ed25519 operations (no hand-rolled crypto).
Uses stdlib `hashlib` for SHA-256 and `hmac` for HMAC-SHA256.
Timing-safe comparison via `hmac.compare_digest` (T-01-01 mitigation).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

KEY_PRIVATE_FILENAME = "ed25519_private.key"
KEY_PUBLIC_FILENAME = "ed25519_public.key"
AUDIT_HMAC_FILENAME = "audit.hmac"
AUDIT_HMAC_SECRET_BYTES = 32
DEV_DEFAULT_HMAC_MARKER = "do-not-use-in-production"


def generate_keypair() -> tuple[bytes, bytes]:
    """Generate an Ed25519 keypair.

    Returns:
        Tuple of (private_key_bytes_32, public_key_bytes_32) in Raw encoding.
    """
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def sign_content(content_bytes: bytes, private_key_bytes: bytes) -> bytes:
    """Sign content with Ed25519.

    Args:
        content_bytes: The content to sign.
        private_key_bytes: 32-byte raw Ed25519 private key.

    Returns:
        64-byte Ed25519 signature.
    """
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    return private_key.sign(content_bytes)


def verify_signature(content_bytes: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
    """Verify an Ed25519 signature.

    Args:
        content_bytes: The content that was signed.
        signature: The 64-byte Ed25519 signature.
        public_key_bytes: 32-byte raw Ed25519 public key.

    Returns:
        True if signature is valid, False otherwise.
    """
    from cryptography.exceptions import InvalidSignature

    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    try:
        public_key.verify(signature, content_bytes)
    except InvalidSignature:
        return False
    return True


def canonical_json(data: dict) -> str:  # type: ignore[type-arg]
    """Produce deterministic JSON serialization.

    Uses sort_keys=True and default=str for datetime handling.
    Critical for content addressing (T-01-04 mitigation).

    Args:
        data: Dictionary to serialize.

    Returns:
        Deterministic JSON string.
    """
    return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))


def sha256_hash(data: dict) -> str:  # type: ignore[type-arg]
    """Compute SHA-256 hash of canonical JSON representation.

    Args:
        data: Dictionary to hash.

    Returns:
        64-character lowercase hex string.
    """
    content = canonical_json(data)
    return hashlib.sha256(content.encode()).hexdigest()


def compute_entry_hash(entry_data: dict, prev_hash: str, secret_key: bytes) -> str:  # type: ignore[type-arg]
    """Compute HMAC-SHA256 hash for an audit ledger entry.

    The hash covers both the previous entry's hash and the current entry's
    canonical JSON, creating a tamper-evident chain.

    Args:
        entry_data: The entry data (excluding hash fields).
        prev_hash: Hash of the previous entry (or "GENESIS" for first entry).
        secret_key: HMAC secret key.

    Returns:
        HMAC-SHA256 hex string.
    """
    message = f"{prev_hash}:{canonical_json(entry_data)}"
    return hmac.new(secret_key, message.encode(), hashlib.sha256).hexdigest()


def _open_excl_write(path: Path, mode: int = 0o600) -> int:
    # O_EXCL refuses to overwrite an existing file — guards against clobbering
    # a prior key that we'd otherwise silently destroy.
    return os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, mode)


def save_keypair_to_dir(directory: Path, private_key: bytes, public_key: bytes) -> None:
    """Persist a raw Ed25519 keypair under ``directory`` with mode 0o600.

    The directory is created if needed and its mode is tightened to 0o700.
    Refuses to overwrite existing key files; delete them first if rotating.

    Raises:
        FileExistsError: If either key file already exists.
        ValueError: If the key byte lengths are wrong (not 32 bytes).
    """
    if len(private_key) != 32 or len(public_key) != 32:
        msg = "Ed25519 keys must be exactly 32 bytes each"
        raise ValueError(msg)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    for name, payload in ((KEY_PRIVATE_FILENAME, private_key), (KEY_PUBLIC_FILENAME, public_key)):
        fd = _open_excl_write(directory / name)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)


def load_keypair_from_dir(directory: Path) -> tuple[bytes, bytes]:
    """Load a raw Ed25519 keypair previously written by ``save_keypair_to_dir``.

    Raises:
        FileNotFoundError: With a remediation hint telling the user to run
            ``ces init`` when either key file is missing.
        ValueError: If either key file is present but not exactly 32 bytes.
    """
    private_path = directory / KEY_PRIVATE_FILENAME
    public_path = directory / KEY_PUBLIC_FILENAME
    if not private_path.exists() or not public_path.exists():
        msg = (
            f"CES signing keys missing at {directory}. "
            "Run `ces init <project-name>` in the project root to generate them."
        )
        raise FileNotFoundError(msg)
    private_bytes = private_path.read_bytes()
    public_bytes = public_path.read_bytes()
    if len(private_bytes) != 32 or len(public_bytes) != 32:
        msg = f"Corrupt Ed25519 key material in {directory}: expected 32 bytes each."
        raise ValueError(msg)
    return private_bytes, public_bytes


def save_audit_hmac_secret(path: Path, secret: bytes) -> None:
    """Persist an HMAC secret to ``path`` with mode 0o600, refusing overwrite."""
    if len(secret) < AUDIT_HMAC_SECRET_BYTES:
        msg = f"Audit HMAC secret must be at least {AUDIT_HMAC_SECRET_BYTES} bytes"
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = _open_excl_write(path)
    try:
        os.write(fd, secret)
    finally:
        os.close(fd)


def generate_audit_hmac_secret() -> bytes:
    """Return a fresh cryptographically-random 32-byte HMAC secret."""
    return secrets.token_bytes(AUDIT_HMAC_SECRET_BYTES)


def load_audit_hmac_secret(path: Path, env_override: str | None = None) -> bytes:
    """Resolve the audit-ledger HMAC secret.

    Resolution order:
        1. ``env_override`` if set and not the development default marker.
        2. File at ``path`` if it exists.
        3. ``FileNotFoundError`` with remediation hint.

    The development-default marker string is rejected explicitly so that a
    user who sets ``CES_AUDIT_HMAC_SECRET`` to the placeholder falls through
    to the file (or the clear error) instead of silently accepting a
    publicly-known secret.
    """
    if env_override and DEV_DEFAULT_HMAC_MARKER not in env_override:
        return env_override.encode("utf-8")
    if path.exists():
        secret = path.read_bytes()
        if len(secret) < AUDIT_HMAC_SECRET_BYTES:
            msg = f"Corrupt audit HMAC secret at {path}: expected >= {AUDIT_HMAC_SECRET_BYTES} bytes."
            raise ValueError(msg)
        return secret
    msg = (
        f"Audit HMAC secret missing at {path}. "
        "Run `ces init <project-name>` to generate one, or set "
        "`CES_AUDIT_HMAC_SECRET` (not the hardcoded development default)."
    )
    raise FileNotFoundError(msg)


def verify_chain(
    entries: list[dict],  # type: ignore[type-arg]
    secret_key: bytes,
    hash_field: str = "entry_hash",
    prev_hash_field: str = "prev_hash",
) -> bool:
    """Verify the integrity of an HMAC-SHA256 hash chain.

    Walks the chain from GENESIS, recomputing each entry's expected hash
    and comparing with timing-safe comparison (T-01-01 mitigation).

    Args:
        entries: Ordered list of audit ledger entries.
        secret_key: HMAC secret key.
        hash_field: Name of the hash field in each entry.
        prev_hash_field: Name of the previous hash field in each entry.

    Returns:
        True if chain is valid, False on first mismatch.
    """
    if not entries:
        return True

    prev_hash = "GENESIS"
    for entry in entries:
        # Extract the entry data without hash fields
        entry_data = {k: v for k, v in entry.items() if k not in (hash_field, prev_hash_field)}

        # Check prev_hash linkage
        if entry.get(prev_hash_field) != prev_hash:
            return False

        # Compute expected hash and compare timing-safe
        expected_hash = compute_entry_hash(entry_data, prev_hash, secret_key)
        if not hmac.compare_digest(entry.get(hash_field, ""), expected_hash):
            return False

        prev_hash = entry[hash_field]

    return True
