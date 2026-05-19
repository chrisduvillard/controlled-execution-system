"""Runtime evidence summary contracts."""

from __future__ import annotations

from ces.execution.runtimes.adapters import CodexRuntimeAdapter


def test_default_runtime_summary_does_not_recommend_approval_from_exit_code() -> None:
    summary, challenge = CodexRuntimeAdapter().summarize_evidence(
        {
            "runtime_name": "codex",
            "description": "Add a feature",
            "exit_code": 0,
            "output_lines": 12,
        }
    )

    assert "Recommendation: approve" not in summary
    assert "not an approval decision" in summary
    assert "ces verify" in summary
    assert "ces proof" in summary
    assert "plausible" in challenge
