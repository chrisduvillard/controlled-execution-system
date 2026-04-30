"""Tests for the PolicyEngine service.

Tests cover:
- File boundary enforcement with glob patterns (WORK-04)
- Tool boundary enforcement (WORK-04)
- Draft-to-approved promotion validation (WORK-05, MODEL-16)
- Combined validation via validate_action
- PolicyViolation dataclass structure
"""

from __future__ import annotations

import pytest

from ces.control.services.policy_engine import PolicyEngine, PolicyViolation
from ces.shared.enums import ArtifactStatus

# ---------------------------------------------------------------------------
# PolicyViolation structure
# ---------------------------------------------------------------------------


class TestPolicyViolation:
    """Test the PolicyViolation dataclass."""

    def test_policy_violation_has_required_fields(self) -> None:
        v = PolicyViolation(
            field="file_access",
            violation_type="file_access",
            message="Access denied",
        )
        assert v.field == "file_access"
        assert v.violation_type == "file_access"
        assert v.message == "Access denied"

    def test_policy_violation_is_frozen(self) -> None:
        v = PolicyViolation(
            field="file_access",
            violation_type="file_access",
            message="test",
        )
        with pytest.raises(AttributeError):
            v.field = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# File boundary enforcement (WORK-04)
# ---------------------------------------------------------------------------


class TestFileAccess:
    """Test file access policy enforcement."""

    def test_file_in_affected_files_allowed(self) -> None:
        assert PolicyEngine.check_file_access(
            file_path="src/ces/models/manifest.py",
            affected_files=["src/ces/models/manifest.py"],
            forbidden_files=[],
        )

    def test_file_in_forbidden_files_denied(self) -> None:
        assert not PolicyEngine.check_file_access(
            file_path="src/ces/secrets.py",
            affected_files=["src/ces/*.py"],
            forbidden_files=["src/ces/secrets.py"],
        )

    def test_file_not_in_affected_files_denied(self) -> None:
        assert not PolicyEngine.check_file_access(
            file_path="src/other/something.py",
            affected_files=["src/ces/models/*.py"],
            forbidden_files=[],
        )

    def test_glob_pattern_in_affected_files(self) -> None:
        assert PolicyEngine.check_file_access(
            file_path="src/ces/models/audit.py",
            affected_files=["src/ces/models/*.py"],
            forbidden_files=[],
        )

    def test_glob_pattern_no_match(self) -> None:
        assert not PolicyEngine.check_file_access(
            file_path="src/ces/models/audit.yaml",
            affected_files=["src/ces/models/*.py"],
            forbidden_files=[],
        )

    def test_forbidden_takes_priority_over_affected(self) -> None:
        """Forbidden files take priority even if matched by affected_files."""
        assert not PolicyEngine.check_file_access(
            file_path="src/ces/models/secret.py",
            affected_files=["src/ces/models/*.py"],
            forbidden_files=["src/ces/models/secret.py"],
        )

    def test_exact_match_in_affected_files(self) -> None:
        assert PolicyEngine.check_file_access(
            file_path="pyproject.toml",
            affected_files=["pyproject.toml"],
            forbidden_files=[],
        )

    def test_empty_affected_files_denies_all(self) -> None:
        assert not PolicyEngine.check_file_access(
            file_path="anything.py",
            affected_files=[],
            forbidden_files=[],
        )

    def test_forbidden_glob_pattern(self) -> None:
        assert not PolicyEngine.check_file_access(
            file_path="tests/fixtures/secret.key",
            affected_files=["tests/fixtures/*"],
            forbidden_files=["tests/fixtures/*.key"],
        )


# ---------------------------------------------------------------------------
# Tool boundary enforcement (WORK-04)
# ---------------------------------------------------------------------------


class TestToolAccess:
    """Test tool access policy enforcement."""

    def test_tool_in_allowed_tools(self) -> None:
        assert PolicyEngine.check_tool_access(
            tool_name="pytest",
            allowed_tools=["pytest", "ruff"],
            forbidden_tools=[],
        )

    def test_tool_in_forbidden_tools(self) -> None:
        assert not PolicyEngine.check_tool_access(
            tool_name="rm",
            allowed_tools=["pytest"],
            forbidden_tools=["rm"],
        )

    def test_empty_allowed_tools_allows_any(self) -> None:
        """Empty allowed_tools = no restriction (allow all non-forbidden)."""
        assert PolicyEngine.check_tool_access(
            tool_name="anything",
            allowed_tools=[],
            forbidden_tools=[],
        )

    def test_forbidden_overrides_allowed(self) -> None:
        """Forbidden tools take priority over allowed."""
        assert not PolicyEngine.check_tool_access(
            tool_name="dangerous",
            allowed_tools=["dangerous", "safe"],
            forbidden_tools=["dangerous"],
        )

    def test_tool_not_in_allowed_tools_denied(self) -> None:
        assert not PolicyEngine.check_tool_access(
            tool_name="unknown",
            allowed_tools=["pytest", "ruff"],
            forbidden_tools=[],
        )

    def test_tool_not_in_forbidden_with_empty_allowed(self) -> None:
        assert PolicyEngine.check_tool_access(
            tool_name="pytest",
            allowed_tools=[],
            forbidden_tools=["rm"],
        )


# ---------------------------------------------------------------------------
# Combined validation via validate_action
# ---------------------------------------------------------------------------


class TestValidateAction:
    """Test combined file + tool validation."""

    def test_all_valid_returns_empty_list(self) -> None:
        violations = PolicyEngine.validate_action(
            file_paths=["src/ces/models/manifest.py"],
            tools_used=["pytest"],
            affected_files=["src/ces/models/*.py"],
            forbidden_files=[],
            allowed_tools=["pytest"],
            forbidden_tools=[],
        )
        assert violations == []

    def test_file_violation_detected(self) -> None:
        violations = PolicyEngine.validate_action(
            file_paths=["src/other/hacked.py"],
            tools_used=[],
            affected_files=["src/ces/models/*.py"],
            forbidden_files=[],
            allowed_tools=[],
            forbidden_tools=[],
        )
        assert len(violations) == 1
        assert violations[0].violation_type == "file_access"

    def test_tool_violation_detected(self) -> None:
        violations = PolicyEngine.validate_action(
            file_paths=[],
            tools_used=["rm"],
            affected_files=[],
            forbidden_files=[],
            allowed_tools=["pytest"],
            forbidden_tools=[],
        )
        assert len(violations) == 1
        assert violations[0].violation_type == "tool_access"

    def test_multiple_violations_returned(self) -> None:
        violations = PolicyEngine.validate_action(
            file_paths=["bad1.py", "bad2.py"],
            tools_used=["forbidden_tool"],
            affected_files=["src/*.py"],
            forbidden_files=[],
            allowed_tools=["safe_tool"],
            forbidden_tools=[],
        )
        assert len(violations) == 3  # 2 file violations + 1 tool violation

    def test_policy_violation_message_is_descriptive(self) -> None:
        violations = PolicyEngine.validate_action(
            file_paths=["nope.py"],
            tools_used=[],
            affected_files=["src/*.py"],
            forbidden_files=[],
            allowed_tools=[],
            forbidden_tools=[],
        )
        assert "nope.py" in violations[0].message


# ---------------------------------------------------------------------------
# Promotion validation (WORK-05, MODEL-16)
# ---------------------------------------------------------------------------


class TestPromotionValidation:
    """Test draft-to-approved promotion rules."""

    def test_valid_promotion(self) -> None:
        """DRAFT artifact with different owner/approver passes."""
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.DRAFT,
            owner="alice",
            approver="bob",
        )
        assert violations == []

    def test_non_draft_cannot_promote(self) -> None:
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.APPROVED,
            owner="alice",
            approver="bob",
        )
        assert len(violations) == 1
        assert violations[0].violation_type == "promotion"
        assert "DRAFT" in violations[0].message

    def test_empty_approver_rejected(self) -> None:
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.DRAFT,
            owner="alice",
            approver="",
        )
        assert any(v.field == "approver" for v in violations)
        assert any("named human approver" in v.message for v in violations)

    def test_whitespace_only_approver_rejected(self) -> None:
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.DRAFT,
            owner="alice",
            approver="   ",
        )
        assert any(v.field == "approver" for v in violations)

    def test_self_approval_rejected(self) -> None:
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.DRAFT,
            owner="alice",
            approver="alice",
        )
        assert any(v.violation_type == "promotion" for v in violations)
        assert any("self-approve" in v.message for v in violations)

    def test_self_approval_with_whitespace_trimmed(self) -> None:
        """Whitespace around names should not bypass self-approval check."""
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.DRAFT,
            owner="alice",
            approver="  alice  ",
        )
        assert any("self-approve" in v.message for v in violations)

    def test_multiple_promotion_violations(self) -> None:
        """Multiple rules can fail simultaneously."""
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.APPROVED,
            owner="alice",
            approver="",
        )
        # Should have at least 2: not DRAFT + empty approver
        assert len(violations) >= 2

    def test_superseded_cannot_promote(self) -> None:
        violations = PolicyEngine.validate_promotion(
            artifact_status=ArtifactStatus.SUPERSEDED,
            owner="alice",
            approver="bob",
        )
        assert len(violations) == 1
        assert "DRAFT" in violations[0].message
