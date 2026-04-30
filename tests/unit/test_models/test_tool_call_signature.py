"""Tests for ToolCallSignature + hash_tool_args (P4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ces.harness.models.tool_call_signature import ToolCallSignature, hash_tool_args


class TestHashToolArgs:
    def test_same_args_same_hash(self) -> None:
        assert hash_tool_args({"path": "data/x", "mode": "r"}) == hash_tool_args({"path": "data/x", "mode": "r"})

    def test_dict_order_does_not_matter(self) -> None:
        a = hash_tool_args({"path": "data/x", "mode": "r"})
        b = hash_tool_args({"mode": "r", "path": "data/x"})
        assert a == b

    def test_different_args_different_hash(self) -> None:
        assert hash_tool_args({"path": "/a"}) != hash_tool_args({"path": "/b"})

    def test_empty_args_is_stable(self) -> None:
        assert hash_tool_args({}) == hash_tool_args({})
        assert hash_tool_args([]) != hash_tool_args({})

    def test_non_json_value_falls_back_to_repr(self) -> None:
        class Custom:
            def __repr__(self) -> str:
                return "Custom()"

        # Should not raise
        h = hash_tool_args({"obj": Custom()})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex


class TestToolCallSignature:
    def test_from_call_builds_signature(self) -> None:
        sig = ToolCallSignature.from_call("Read", {"path": "x.py"})
        assert sig.tool_name == "Read"
        assert len(sig.args_hash) == 64

    def test_equality_is_structural(self) -> None:
        a = ToolCallSignature.from_call("Read", {"path": "x.py"})
        b = ToolCallSignature.from_call("Read", {"path": "x.py"})
        assert a == b

    def test_different_args_not_equal(self) -> None:
        a = ToolCallSignature.from_call("Read", {"path": "x.py"})
        b = ToolCallSignature.from_call("Read", {"path": "y.py"})
        assert a != b

    def test_different_tools_not_equal(self) -> None:
        a = ToolCallSignature.from_call("Read", {"path": "x.py"})
        b = ToolCallSignature.from_call("Write", {"path": "x.py"})
        assert a != b

    def test_signature_is_frozen(self) -> None:
        sig = ToolCallSignature.from_call("Read", {})
        with pytest.raises(ValidationError):
            sig.tool_name = "Write"  # type: ignore[misc]
