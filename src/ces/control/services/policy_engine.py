"""Policy engine for manifest boundary enforcement and promotion rules.

Implements:
- WORK-04: File and tool boundary enforcement using manifest declarations.
- WORK-05: Draft-to-approved promotion rules with separation of duties (MODEL-16).

The PolicyEngine is stateless -- all methods are static and operate on
the boundary declarations from a TaskManifest. This ensures determinism
(no LLM, no external state) as required by control plane constraints.

File boundary checks use fnmatch for glob pattern support, allowing
manifests to declare patterns like "src/ces/models/*.py".

Exports:
    PolicyViolation: Frozen dataclass describing a single policy violation.
    PolicyEngine: Static methods for boundary checking and promotion validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from ces.shared.enums import ArtifactStatus


@dataclass(frozen=True)
class PolicyViolation:
    """A policy violation detected by the policy engine.

    Attributes:
        field: Which policy field was violated (e.g., "file_access", "tool_access").
        violation_type: Category of violation (e.g., "file_access", "tool_access", "promotion").
        message: Human-readable description of the violation.
    """

    field: str
    violation_type: str
    message: str


class PolicyEngine:
    """Enforces manifest boundaries and promotion rules.

    WORK-04: Enforces allowed_files, forbidden_files, allowed_tools, forbidden_tools.
    WORK-05: Enforces draft-to-approved promotion rules (MODEL-16).

    All methods are static -- the PolicyEngine is stateless by design.
    Determinism is guaranteed: no LLM calls, no external state, pure logic.
    """

    @staticmethod
    def check_file_access(
        file_path: str,
        affected_files: list[str],
        forbidden_files: list[str],
    ) -> bool:
        """Check if a file access is allowed by manifest boundaries.

        Returns True if:
        - file matches a pattern in affected_files AND
        - file does NOT match any pattern in forbidden_files

        Uses fnmatch for glob pattern support (e.g., "src/ces/models/*.py").
        Forbidden files take priority over affected files.

        Args:
            file_path: The file path to check.
            affected_files: List of allowed file patterns (glob supported).
            forbidden_files: List of forbidden file patterns (glob supported).

        Returns:
            True if access is allowed, False otherwise.
        """
        # Check forbidden first (takes priority -- T-07-03 mitigation)
        for pattern in forbidden_files:
            if fnmatch(file_path, pattern):
                return False

        # Check allowed (must match at least one affected_files pattern)
        for pattern in affected_files:
            if fnmatch(file_path, pattern):
                return True

        return False  # Not in affected_files = not allowed

    @staticmethod
    def check_tool_access(
        tool_name: str,
        allowed_tools: list[str],
        forbidden_tools: list[str],
    ) -> bool:
        """Check if a tool usage is allowed by manifest boundaries.

        Returns True if:
        - tool is NOT in forbidden_tools AND
        - (allowed_tools is empty OR tool is in allowed_tools)

        Empty allowed_tools means no restriction (all non-forbidden tools allowed).
        Forbidden tools always take priority.

        Args:
            tool_name: The tool name to check.
            allowed_tools: List of allowed tool names. Empty = no restriction.
            forbidden_tools: List of forbidden tool names.

        Returns:
            True if access is allowed, False otherwise.
        """
        if tool_name in forbidden_tools:
            return False
        if not allowed_tools:
            return True  # Empty allowed_tools = no restriction
        return tool_name in allowed_tools

    @staticmethod
    def validate_action(
        file_paths: list[str],
        tools_used: list[str],
        affected_files: list[str],
        forbidden_files: list[str],
        allowed_tools: list[str],
        forbidden_tools: list[str],
    ) -> list[PolicyViolation]:
        """Validate a set of file accesses and tool usages against manifest boundaries.

        Checks all file paths against affected_files/forbidden_files and
        all tools against allowed_tools/forbidden_tools.

        Args:
            file_paths: Files being accessed.
            tools_used: Tools being used.
            affected_files: Allowed file patterns from manifest.
            forbidden_files: Forbidden file patterns from manifest.
            allowed_tools: Allowed tool names from manifest.
            forbidden_tools: Forbidden tool names from manifest.

        Returns:
            List of PolicyViolation objects (empty = all checks pass).
        """
        violations: list[PolicyViolation] = []

        for fp in file_paths:
            if not PolicyEngine.check_file_access(fp, affected_files, forbidden_files):
                violations.append(
                    PolicyViolation(
                        field="file_access",
                        violation_type="file_access",
                        message=(f"File access denied: {fp} is not in affected_files or is in forbidden_files"),
                    )
                )

        for tool in tools_used:
            if not PolicyEngine.check_tool_access(tool, allowed_tools, forbidden_tools):
                violations.append(
                    PolicyViolation(
                        field="tool_access",
                        violation_type="tool_access",
                        message=(f"Tool access denied: {tool} is not in allowed_tools or is in forbidden_tools"),
                    )
                )

        return violations

    @staticmethod
    def validate_promotion(
        artifact_status: ArtifactStatus,
        owner: str,
        approver: str,
    ) -> list[PolicyViolation]:
        """Validate draft-to-approved promotion rules (WORK-05, MODEL-16).

        Rules:
        - Artifact must be in DRAFT status (only drafts can be promoted).
        - Approver must be a named human (non-empty string after stripping).
        - Approver must not be the artifact owner (no self-approval -- separation of duties).

        Args:
            artifact_status: Current status of the artifact.
            owner: The artifact owner/creator identifier.
            approver: The proposed approver identifier.

        Returns:
            List of PolicyViolation objects (empty = promotion is valid).
        """
        violations: list[PolicyViolation] = []

        if artifact_status != ArtifactStatus.DRAFT:
            violations.append(
                PolicyViolation(
                    field="status",
                    violation_type="promotion",
                    message=(f"Only DRAFT artifacts can be promoted. Current status: {artifact_status.value}"),
                )
            )

        if not approver or not approver.strip():
            violations.append(
                PolicyViolation(
                    field="approver",
                    violation_type="promotion",
                    message="Promotion requires a named human approver",
                )
            )

        if approver and owner and approver.strip() == owner.strip():
            violations.append(
                PolicyViolation(
                    field="approver",
                    violation_type="promotion",
                    message="Owner cannot self-approve promotion (separation of duties)",
                )
            )

        return violations
