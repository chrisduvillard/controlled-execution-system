"""Tests for CES cryptographic utilities.

Validates Ed25519 signing, SHA-256 hashing, HMAC-SHA256 chain integrity,
and deterministic canonical JSON serialization.
"""

from __future__ import annotations

import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ces.shared.crypto import (
    AUDIT_HMAC_FILENAME,
    AUDIT_HMAC_SECRET_BYTES,
    KEY_PRIVATE_FILENAME,
    KEY_PUBLIC_FILENAME,
    canonical_json,
    compute_entry_hash,
    generate_audit_hmac_secret,
    generate_keypair,
    load_audit_hmac_secret,
    load_keypair_from_dir,
    save_audit_hmac_secret,
    save_keypair_to_dir,
    sha256_hash,
    sign_content,
    verify_chain,
    verify_signature,
)


class TestGenerateKeypair:
    """Ed25519 keypair generation."""

    def test_returns_tuple_of_bytes(self) -> None:
        private_key, public_key = generate_keypair()
        assert isinstance(private_key, bytes)
        assert isinstance(public_key, bytes)

    def test_private_key_is_32_bytes(self) -> None:
        private_key, _ = generate_keypair()
        assert len(private_key) == 32

    def test_public_key_is_32_bytes(self) -> None:
        _, public_key = generate_keypair()
        assert len(public_key) == 32

    def test_different_keypairs_are_unique(self) -> None:
        kp1 = generate_keypair()
        kp2 = generate_keypair()
        assert kp1[0] != kp2[0]
        assert kp1[1] != kp2[1]


class TestSignAndVerify:
    """Ed25519 signing and verification round-trip."""

    def test_sign_verify_roundtrip(self, ed25519_private_key: bytes, ed25519_public_key: bytes) -> None:
        """Sign then verify should return True."""
        content = b"test content to sign"
        signature = sign_content(content, ed25519_private_key)
        assert verify_signature(content, signature, ed25519_public_key) is True

    def test_signature_is_64_bytes(self, ed25519_private_key: bytes) -> None:
        content = b"test content"
        signature = sign_content(content, ed25519_private_key)
        assert len(signature) == 64

    def test_tampered_content_fails_verification(self, ed25519_private_key: bytes, ed25519_public_key: bytes) -> None:
        """Verification should fail for tampered content."""
        content = b"original content"
        signature = sign_content(content, ed25519_private_key)
        tampered = b"tampered content"
        assert verify_signature(tampered, signature, ed25519_public_key) is False

    def test_wrong_public_key_fails_verification(self, ed25519_private_key: bytes) -> None:
        """Verification should fail with a different public key."""
        content = b"test content"
        signature = sign_content(content, ed25519_private_key)
        _, wrong_public_key = generate_keypair()
        assert verify_signature(content, signature, wrong_public_key) is False


class TestSha256Hash:
    """SHA-256 content hashing for truth artifact integrity."""

    def test_returns_64_char_hex_string(self) -> None:
        result = sha256_hash({"key": "value"})
        assert isinstance(result, str)
        assert len(result) == 64

    def test_deterministic_for_same_input(self) -> None:
        data = {"name": "test", "count": 42}
        assert sha256_hash(data) == sha256_hash(data)

    def test_different_input_different_hash(self) -> None:
        assert sha256_hash({"a": 1}) != sha256_hash({"a": 2})

    def test_hex_characters_only(self) -> None:
        result = sha256_hash({"test": True})
        assert all(c in "0123456789abcdef" for c in result)


class TestCanonicalJson:
    """Deterministic JSON serialization for content addressing."""

    def test_same_output_for_different_insertion_order(self) -> None:
        """Dicts with same keys/values but different insertion order should produce identical JSON."""
        dict1 = {"b": 2, "a": 1, "c": 3}
        dict2 = {"c": 3, "a": 1, "b": 2}
        assert canonical_json(dict1) == canonical_json(dict2)

    def test_handles_datetime_values(self) -> None:
        """datetime values should be serialized via default=str."""
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = canonical_json({"timestamp": dt})
        assert "2026" in result

    def test_sorted_keys(self) -> None:
        result = canonical_json({"z": 1, "a": 2})
        assert result.index('"a"') < result.index('"z"')


class TestComputeEntryHash:
    """HMAC-SHA256 entry hash for audit ledger chain integrity."""

    def test_returns_hex_string(self) -> None:
        result = compute_entry_hash(
            entry_data={"event": "test"},
            prev_hash="GENESIS",
            secret_key=b"test-secret",
        )
        assert isinstance(result, str)
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_for_same_input(self) -> None:
        data = {"event": "approval", "actor": "agent-1"}
        key = b"consistent-secret"
        h1 = compute_entry_hash(data, "prev123", key)
        h2 = compute_entry_hash(data, "prev123", key)
        assert h1 == h2

    def test_different_prev_hash_different_result(self) -> None:
        data = {"event": "test"}
        key = b"secret"
        h1 = compute_entry_hash(data, "hash1", key)
        h2 = compute_entry_hash(data, "hash2", key)
        assert h1 != h2


class TestVerifyChain:
    """HMAC-SHA256 chain verification for audit ledger integrity."""

    def _build_chain(self, entries_data: list[dict], secret_key: bytes) -> list[dict]:
        """Helper: build a valid chain from a list of entry data dicts."""
        chain: list[dict] = []
        prev_hash = "GENESIS"
        for data in entries_data:
            entry_hash = compute_entry_hash(data, prev_hash, secret_key)
            entry = {**data, "entry_hash": entry_hash, "prev_hash": prev_hash}
            chain.append(entry)
            prev_hash = entry_hash
        return chain

    def test_valid_chain_of_three_entries(self) -> None:
        """A properly constructed chain of 3+ entries should verify True."""
        secret = b"chain-secret"
        entries_data = [
            {"event": "first", "seq": 1},
            {"event": "second", "seq": 2},
            {"event": "third", "seq": 3},
        ]
        chain = self._build_chain(entries_data, secret)
        assert verify_chain(chain, secret) is True

    def test_tampered_middle_entry_fails(self) -> None:
        """Changing data in the middle entry should break verification."""
        secret = b"chain-secret"
        entries_data = [
            {"event": "first", "seq": 1},
            {"event": "second", "seq": 2},
            {"event": "third", "seq": 3},
        ]
        chain = self._build_chain(entries_data, secret)
        # Tamper with the middle entry
        chain[1]["event"] = "TAMPERED"
        assert verify_chain(chain, secret) is False

    def test_reordered_chain_fails(self) -> None:
        """Changing the order of entries should break verification."""
        secret = b"chain-secret"
        entries_data = [
            {"event": "first", "seq": 1},
            {"event": "second", "seq": 2},
            {"event": "third", "seq": 3},
        ]
        chain = self._build_chain(entries_data, secret)
        # Swap first and second entries
        chain[0], chain[1] = chain[1], chain[0]
        assert verify_chain(chain, secret) is False

    def test_single_entry_chain_verifies(self) -> None:
        """A chain with a single entry should verify True."""
        secret = b"chain-secret"
        chain = self._build_chain([{"event": "only"}], secret)
        assert verify_chain(chain, secret) is True

    def test_empty_chain_verifies(self) -> None:
        """An empty chain should verify True (vacuously true)."""
        assert verify_chain([], b"secret") is True


class TestKeypairPersistence:
    """Round-trip persistence of Ed25519 keypairs to disk."""

    def test_save_then_load_returns_same_bytes(self, tmp_path: Path) -> None:
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        loaded_priv, loaded_pub = load_keypair_from_dir(tmp_path)
        assert loaded_priv == priv
        assert loaded_pub == pub

    def test_save_creates_files_with_expected_names(self, tmp_path: Path) -> None:
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        assert (tmp_path / KEY_PRIVATE_FILENAME).exists()
        assert (tmp_path / KEY_PUBLIC_FILENAME).exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_save_writes_files_mode_0600(self, tmp_path: Path) -> None:
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        for name in (KEY_PRIVATE_FILENAME, KEY_PUBLIC_FILENAME):
            mode = stat.S_IMODE(os.stat(tmp_path / name).st_mode)
            assert mode == 0o600, f"{name} is 0o{mode:o}, expected 0o600"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_save_tightens_directory_mode_0700(self, tmp_path: Path) -> None:
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        mode = stat.S_IMODE(os.stat(tmp_path).st_mode)
        assert mode == 0o700, f"directory is 0o{mode:o}, expected 0o700"

    def test_save_refuses_to_overwrite_existing_key(self, tmp_path: Path) -> None:
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        priv2, pub2 = generate_keypair()
        with pytest.raises(FileExistsError):
            save_keypair_to_dir(tmp_path, priv2, pub2)

    def test_save_rejects_wrong_length_keys(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            save_keypair_to_dir(tmp_path, b"x" * 31, b"y" * 32)

    def test_load_missing_keys_raises_with_remediation(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="ces init"):
            load_keypair_from_dir(tmp_path)

    def test_load_corrupt_keys_raises(self, tmp_path: Path) -> None:
        (tmp_path / KEY_PRIVATE_FILENAME).write_bytes(b"too-short")
        (tmp_path / KEY_PUBLIC_FILENAME).write_bytes(b"too-short")
        with pytest.raises(ValueError, match="Corrupt"):
            load_keypair_from_dir(tmp_path)

    def test_round_trip_supports_signing(self, tmp_path: Path) -> None:
        """Keys loaded from disk must still sign and verify end-to-end."""
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)
        loaded_priv, loaded_pub = load_keypair_from_dir(tmp_path)
        signature = sign_content(b"payload", loaded_priv)
        assert verify_signature(b"payload", signature, loaded_pub) is True

    def test_save_swallows_chmod_oserror(self, tmp_path: Path, monkeypatch) -> None:
        """save_keypair_to_dir continues even when chmod-ing the directory raises OSError.

        Some filesystems (Windows-mounted shares, NFS, certain tmpfs variants)
        refuse chmod. The save path must still succeed and write the keys.
        """
        from ces.shared import crypto as crypto_mod

        def _raising_chmod(*args, **kwargs):
            raise OSError("chmod not supported")

        monkeypatch.setattr(crypto_mod.os, "chmod", _raising_chmod)
        priv, pub = generate_keypair()
        save_keypair_to_dir(tmp_path, priv, pub)  # must not raise
        assert (tmp_path / KEY_PRIVATE_FILENAME).read_bytes() == priv
        assert (tmp_path / KEY_PUBLIC_FILENAME).read_bytes() == pub


class TestAuditHmacPersistence:
    """Persistence + resolution of the audit-ledger HMAC secret."""

    def test_generate_returns_random_32_bytes(self) -> None:
        s1 = generate_audit_hmac_secret()
        s2 = generate_audit_hmac_secret()
        assert len(s1) == AUDIT_HMAC_SECRET_BYTES
        assert s1 != s2

    def test_save_then_load_from_file(self, tmp_path: Path) -> None:
        secret = generate_audit_hmac_secret()
        path = tmp_path / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, secret)
        assert load_audit_hmac_secret(path) == secret

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_save_writes_file_mode_0600(self, tmp_path: Path) -> None:
        secret = generate_audit_hmac_secret()
        path = tmp_path / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, secret)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600

    def test_save_refuses_to_overwrite_existing_secret(self, tmp_path: Path) -> None:
        path = tmp_path / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, generate_audit_hmac_secret())
        with pytest.raises(FileExistsError):
            save_audit_hmac_secret(path, generate_audit_hmac_secret())

    def test_save_rejects_short_secrets(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            save_audit_hmac_secret(tmp_path / AUDIT_HMAC_FILENAME, b"too-short")

    def test_env_override_preferred_over_file(self, tmp_path: Path) -> None:
        file_secret = generate_audit_hmac_secret()
        path = tmp_path / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, file_secret)
        override = "ci-override-secret-at-least-32-bytes-long"
        assert load_audit_hmac_secret(path, env_override=override) == override.encode("utf-8")

    def test_env_override_with_dev_default_falls_through(self, tmp_path: Path) -> None:
        """If the env value is the hardcoded dev placeholder, ignore it and use the file."""
        file_secret = generate_audit_hmac_secret()
        path = tmp_path / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, file_secret)
        dev_default = "ces-dev-hmac-secret-do-not-use-in-production"
        assert load_audit_hmac_secret(path, env_override=dev_default) == file_secret

    def test_save_secret_swallows_chmod_oserror(self, tmp_path: Path, monkeypatch) -> None:
        """save_audit_hmac_secret tolerates filesystems where chmod is unsupported."""
        from ces.shared import crypto as crypto_mod

        def _raising_chmod(*args, **kwargs):
            raise OSError("chmod not supported")

        monkeypatch.setattr(crypto_mod.os, "chmod", _raising_chmod)
        secret = generate_audit_hmac_secret()
        path = tmp_path / "subdir" / AUDIT_HMAC_FILENAME
        save_audit_hmac_secret(path, secret)  # must not raise
        assert path.read_bytes() == secret

    def test_load_missing_file_and_no_override_raises_with_remediation(self, tmp_path: Path) -> None:
        path = tmp_path / AUDIT_HMAC_FILENAME
        with pytest.raises(FileNotFoundError, match="ces init"):
            load_audit_hmac_secret(path)

    def test_load_corrupt_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / AUDIT_HMAC_FILENAME
        path.write_bytes(b"too-short")
        with pytest.raises(ValueError, match="Corrupt"):
            load_audit_hmac_secret(path)
