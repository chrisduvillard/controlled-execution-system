"""Cross-step execution risk monitor.

The monitor is deterministic and local: callers provide a compact sequence of
command events, and the service returns structured findings for temporal
anti-patterns that are easy to miss when looking at one command at a time.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from ces.execution.secrets import scrub_secrets_from_text
from ces.harness.models.execution_risk import (
    ExecutionCommandEvent,
    ExecutionRiskFinding,
    ExecutionRiskKind,
    ExecutionRiskSeverity,
)

_PROXY_VALIDATION_RE = re.compile(r"\b(validation passed|looks good|import ok|smoke ok|compiles?)\b", re.IGNORECASE)
_TEST_COMMAND_RE = re.compile(
    r"\b(pytest|python\s+-m\s+unittest|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|yarn\s+(?:run\s+)?test|go\s+test|cargo\s+test|rspec|vitest)\b",
    re.IGNORECASE,
)
_COMPILE_ONLY_RE = re.compile(
    r"\b(py_compile|compileall|tsc\s+--?noEmit|go\s+test\s+-c|cargo\s+check)\b", re.IGNORECASE
)
_TIMEOUT_RE = re.compile(r"\b(timeout|timed out|exit code 124)\b", re.IGNORECASE)
_DESTRUCTIVE_RE = re.compile(
    r"(^|\s)(rm\s+-rf|git\s+clean\s+-fd|git\s+reset\s+--hard|truncate\s+-s\s+0|find\b.*\b-delete\b)",
    re.IGNORECASE,
)


def _safe_command(command: str) -> str:
    """Return a command string safe enough for evidence surfaces."""
    return scrub_secrets_from_text(command)[:500]


class ExecutionRiskMonitor:
    """Analyze command sequences for cross-step execution risks."""

    def analyze(
        self,
        events: Sequence[ExecutionCommandEvent],
        *,
        changed_files: Iterable[str] = (),
        behavioral_change: bool = False,
    ) -> list[ExecutionRiskFinding]:
        """Return deterministic findings for a command trajectory."""
        changed_file_tuple = tuple(changed_files)
        findings: list[ExecutionRiskFinding] = []
        findings.extend(self._repeated_failures(events))
        findings.extend(self._timeout_loops(events))
        findings.extend(self._destructive_after_success(events))
        findings.extend(self._proxy_validation(events))
        findings.extend(self._compile_only_validation(events, changed_file_tuple, behavioral_change))
        findings.extend(self._shallow_validation(events, changed_file_tuple, behavioral_change))
        return sorted(findings, key=lambda finding: (finding.kind.value, finding.command, finding.message))

    def _repeated_failures(self, events: Sequence[ExecutionCommandEvent]) -> list[ExecutionRiskFinding]:
        failed_commands = [event.command for event in events if event.exit_code not in (None, 0)]
        counts = Counter(failed_commands)
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.REPEATED_FAILURE,
                severity=ExecutionRiskSeverity.HIGH,
                command=_safe_command(command),
                message=f"Command failed repeatedly ({count} times): {_safe_command(command)}",
                recommended_action="Stop retrying the same failing command; inspect the error and change strategy before re-running.",
                evidence_refs=(f"command:{_safe_command(command)}",),
            )
            for command, count in counts.items()
            if count >= 3
        ]

    def _timeout_loops(self, events: Sequence[ExecutionCommandEvent]) -> list[ExecutionRiskFinding]:
        timed_out = [
            event.command for event in events if event.exit_code == 124 or _TIMEOUT_RE.search(event.output_excerpt)
        ]
        counts = Counter(timed_out)
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.TIMEOUT_LOOP,
                severity=ExecutionRiskSeverity.HIGH,
                command=_safe_command(command),
                message=f"Command appears to be timing out repeatedly ({count} times): {_safe_command(command)}",
                recommended_action="Reduce scope, inspect logs, or increase timeout only after proving the command is making progress.",
                evidence_refs=(f"command:{_safe_command(command)}",),
            )
            for command, count in counts.items()
            if count >= 2
        ]

    def _destructive_after_success(self, events: Sequence[ExecutionCommandEvent]) -> list[ExecutionRiskFinding]:
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.DESTRUCTIVE_AFTER_SUCCESS,
                severity=ExecutionRiskSeverity.CRITICAL,
                command=_safe_command(event.command),
                message=f"Destructive command ran after a successful verification point: {_safe_command(event.command)}",
                recommended_action="Re-run validation and regenerate evidence before claiming completion.",
                evidence_refs=(f"command:{_safe_command(event.command)}",),
            )
            for event in events
            if event.after_success and _DESTRUCTIVE_RE.search(event.command)
        ]

    def _proxy_validation(self, events: Sequence[ExecutionCommandEvent]) -> list[ExecutionRiskFinding]:
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.PROXY_VALIDATION,
                severity=ExecutionRiskSeverity.MEDIUM,
                command=_safe_command(event.command),
                message="Command/output looks like a proxy validation rather than project verification.",
                recommended_action="Run the project's real test/evaluator command and preserve its artifact.",
                evidence_refs=(f"command:{_safe_command(event.command)}",),
            )
            for event in events
            if event.exit_code in (None, 0)
            and _PROXY_VALIDATION_RE.search(f"{event.command}\n{event.output_excerpt}")
            and _TEST_COMMAND_RE.search(event.command) is None
        ]

    def _compile_only_validation(
        self,
        events: Sequence[ExecutionCommandEvent],
        changed_files: tuple[str, ...],
        behavioral_change: bool,
    ) -> list[ExecutionRiskFinding]:
        if not behavioral_change or not changed_files:
            return []
        compile_events = [
            event for event in events if _COMPILE_ONLY_RE.search(event.command) and event.exit_code in (None, 0)
        ]
        real_tests = [
            event for event in events if _TEST_COMMAND_RE.search(event.command) and event.exit_code in (None, 0)
        ]
        if not compile_events or real_tests:
            return []
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.COMPILE_ONLY_VALIDATION,
                severity=ExecutionRiskSeverity.HIGH,
                command=_safe_command(compile_events[-1].command),
                message="Behavioral change was validated with compile/type checks but no project test/evaluator command.",
                recommended_action="Run behavioral tests or an evaluator covering the changed behavior before completing.",
                evidence_refs=tuple(f"file:{path}" for path in changed_files[:5]),
            )
        ]

    def _shallow_validation(
        self,
        events: Sequence[ExecutionCommandEvent],
        changed_files: tuple[str, ...],
        behavioral_change: bool,
    ) -> list[ExecutionRiskFinding]:
        if not behavioral_change and not changed_files:
            return []
        successful_events = [event for event in events if event.exit_code in (None, 0)]
        real_tests = [event for event in successful_events if _TEST_COMMAND_RE.search(event.command)]
        proxy_events = [
            event
            for event in successful_events
            if _PROXY_VALIDATION_RE.search(f"{event.command}\n{event.output_excerpt}")
        ]
        if real_tests or not proxy_events:
            return []
        return [
            ExecutionRiskFinding(
                kind=ExecutionRiskKind.SHALLOW_VALIDATION,
                severity=ExecutionRiskSeverity.MEDIUM,
                command=_safe_command(proxy_events[-1].command),
                message="Validation sequence appears shallow for the changed surface.",
                recommended_action="Replace shallow checks with project-level tests/evaluators tied to the affected behavior.",
                evidence_refs=tuple(f"file:{path}" for path in changed_files[:5]),
            )
        ]
