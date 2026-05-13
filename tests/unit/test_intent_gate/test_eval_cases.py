from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ces.intent_gate.classifier import classify_intent

_FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "intent_gate" / "eval_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    with _FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
        cases = json.load(fixture_file)
    assert isinstance(cases, list)
    return cases


def test_intent_gate_eval_fixture_cases_classify_to_expected_decisions() -> None:
    cases = _load_cases()

    assert [case["id"] for case in cases] == [
        "clear_ci_task_proceeds",
        "low_risk_readme_wording_assumes",
        "high_risk_auth_without_acceptance_asks",
        "high_risk_database_delete_noninteractive_blocks",
    ]

    for case in cases:
        preflight = classify_intent(
            request=case["request"],
            constraints=tuple(case.get("constraints", ())),
            acceptance_criteria=tuple(case.get("acceptance_criteria", ())),
            must_not_break=tuple(case.get("must_not_break", ())),
            project_mode=case.get("project_mode", "maintenance"),
            non_interactive=case.get("non_interactive", False),
        )

        assert preflight.decision == case["expected_decision"], case["id"]
