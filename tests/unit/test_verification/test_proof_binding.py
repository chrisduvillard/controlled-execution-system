"""Tests for objective-bound proof binding fingerprints."""

from __future__ import annotations

import json

from ces.verification.completion_contract import (
    AcceptanceCriterion,
    BehaviorDelta,
    CompletionContract,
    OfficialEvaluator,
    RealityBoundaryContract,
    SuccessPredicate,
    VerificationCommand,
)


def _legacy_binding_hash(payload: dict) -> str:
    import hashlib
    import json

    material = {
        "schema_version": "1.0",
        "project_mode": payload.get("runtime", {}).get("project_mode", "unknown"),
        "objective": payload["request"],
        "project_type": payload["project_type"],
        "acceptance_criteria": tuple(
            {"id": item["id"], "text": item["text"]} for item in payload.get("acceptance_criteria", [])
        ),
        "runtime_context": {},
        "behavior_delta": {"added": [], "modified": [], "removed": [], "preserved": [], "unknown": []},
        "verification_commands": tuple(
            {
                "id": item["id"],
                "kind": item["kind"],
                "command": item["command"],
                "required": item.get("required", True),
                "cwd": item.get("cwd", "."),
                "timeout_seconds": item.get("timeout_seconds", 120),
                "expected_exit_codes": tuple(item.get("expected_exit_codes", [0])),
            }
            for item in payload.get("inferred_commands", [])
        ),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _contract(**overrides) -> CompletionContract:
    payload = {
        "request": "Add invoice notes to CSV exports",
        "project_type": "python-cli",
        "acceptance_criteria": (AcceptanceCriterion(id="AC-001", text="CSV exports include notes"),),
        "inferred_commands": (
            VerificationCommand(id="tests", kind="test", command="pytest", expected_exit_codes=(0,)),
        ),
        "runtime": {
            "name": "codex",
            "project_mode": "brownfield",
            "constraints": ["keep CSV headers stable"],
            "must_not_break": ["existing CSV importers"],
            "source_of_truth": "README.md and current tests",
            "critical_flows": ["export invoices", "import exported CSV"],
        },
        "behavior_delta": BehaviorDelta(
            modified=("CSV export writes an optional notes column.",),
            preserved=("Existing CSV importers still accept old exports.",),
        ),
    }
    payload.update(overrides)
    return CompletionContract(**payload)


def test_proof_binding_hash_is_stable_for_same_objective_context() -> None:
    from ces.verification.proof_binding import build_proof_binding

    first = build_proof_binding(_contract())
    second = build_proof_binding(_contract())

    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64
    assert first.to_dict()["project_mode"] == "brownfield"
    assert first.to_dict()["objective"] == "Add invoice notes to CSV exports"


def test_proof_binding_hash_changes_when_objective_changes() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(_contract(request="Add supplier notes to PDFs")).content_hash

    assert changed != original


def test_proof_binding_hash_changes_when_brownfield_constraints_change() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(
        _contract(
            runtime={
                "name": "codex",
                "project_mode": "brownfield",
                "constraints": ["keep CSV headers stable"],
                "must_not_break": ["legacy invoice totals"],
                "source_of_truth": "docs/domain.md",
                "critical_flows": ["export invoices"],
            }
        )
    ).content_hash

    assert changed != original


def test_proof_binding_hash_changes_when_verification_commands_change() -> None:
    from ces.verification.proof_binding import build_proof_binding

    original = build_proof_binding(_contract()).content_hash
    changed = build_proof_binding(
        _contract(
            inferred_commands=(
                VerificationCommand(id="tests", kind="test", command="pytest -q", expected_exit_codes=(0,)),
            )
        )
    ).content_hash

    assert changed != original


def test_proof_binding_scrubs_inline_secret_before_export_and_hash() -> None:
    from ces.verification.proof_binding import build_proof_binding

    binding = build_proof_binding(
        _contract(
            inferred_commands=(
                VerificationCommand(
                    id="smoke",
                    kind="smoke",
                    command="OPENAI_API_KEY=sk-tes...alue python app.py",
                    expected_exit_codes=(0,),
                ),
            )
        )
    )

    exported = str(binding.to_dict())
    assert "sk-tes...alue" not in exported
    assert "OPENAI_API_KEY=<REDACTED>" in exported


def test_proof_binding_preserves_legacy_hash_when_reality_boundary_is_absent() -> None:
    from ces.verification.proof_binding import build_proof_binding_from_payload, proof_binding_hash_from_payload

    payload = {
        "request": "Add invoice notes to CSV exports",
        "project_type": "python-cli",
        "acceptance_criteria": [{"id": "AC-001", "text": "CSV exports include notes"}],
        "inferred_commands": [
            {"id": "tests", "kind": "test", "command": "pytest", "expected_exit_codes": [0]},
        ],
        "runtime": {"name": "codex"},
    }

    binding = build_proof_binding_from_payload(payload)

    assert binding.schema_version == "1.0"
    assert proof_binding_hash_from_payload(payload) == _legacy_binding_hash(payload)
    assert "reality_boundary" not in binding.to_dict()


def test_proof_binding_exports_reality_boundary_hashes_without_raw_predicates_or_commands() -> None:
    from ces.verification.proof_binding import build_proof_binding

    binding = build_proof_binding(
        _contract(
            reality_boundary=RealityBoundaryContract(
                success_predicates=(SuccessPredicate(id="AC-001", text="private acceptance detail"),),
                official_evaluators=(
                    OfficialEvaluator(
                        id="VC-001",
                        command_id="VC-001",
                        kind="test",
                        command="uv run pytest tests/private_flow.py -q",
                        cwd="/home/chris/private/project",
                    ),
                ),
            ).with_predicate_hash()
        )
    )

    payload = binding.to_dict()
    exported = json.dumps(payload)

    assert payload["schema_version"] == "1.1"
    assert "private acceptance detail" not in exported
    assert "uv run pytest tests/private_flow.py -q" not in exported
    assert "/home/chris/private/project" not in exported
    assert payload["reality_boundary"]["success_predicates"][0]["text_sha256"]
    assert payload["reality_boundary"]["official_evaluators"][0]["command_sha256"]


def test_proof_binding_recomputes_hashes_when_raw_reality_boundary_material_changes() -> None:
    from ces.verification.proof_binding import proof_binding_hash_from_payload

    contract = _contract(
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text="original measurable outcome"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="test",
                    command="uv run pytest tests/original.py -q",
                    cwd=".",
                ),
            ),
        ).with_predicate_hash()
    )
    stored = contract.to_dict()
    tampered = json.loads(json.dumps(stored))
    tampered["reality_boundary"]["success_predicates"][0]["text"] = "weakened measurable outcome"
    tampered["reality_boundary"]["official_evaluators"][0]["command"] = "true"

    assert proof_binding_hash_from_payload(tampered) != proof_binding_hash_from_payload(stored)


def test_proof_binding_hash_changes_when_raw_reality_boundary_material_is_removed_but_stale_hashes_remain() -> None:
    from ces.verification.completion_contract import ProtectedSurface, _contract_storage_dict
    from ces.verification.proof_binding import proof_binding_hash_from_payload

    contract = _contract(
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text="original measurable outcome"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="test",
                    command="uv run pytest tests/original.py -q",
                    cwd="tests",
                ),
            ),
            protected_surfaces=(ProtectedSurface(path="tests/original.py", reason="must verify behavior"),),
            allowed_test_paths=("tests/original.py",),
            denied_test_paths=("tests/mutated.py",),
        ).with_predicate_hash()
    )
    stored = _contract_storage_dict(contract)
    tampered = json.loads(json.dumps(stored))
    predicate = tampered["reality_boundary"]["success_predicates"][0]
    evaluator = tampered["reality_boundary"]["official_evaluators"][0]
    surface = tampered["reality_boundary"]["protected_surfaces"][0]
    predicate.pop("text")
    evaluator["command"] = ""
    evaluator.pop("cwd")
    surface.pop("path")
    surface["reason"] = ""
    tampered["reality_boundary"]["allowed_test_paths"] = []
    tampered["reality_boundary"].pop("denied_test_paths")

    assert proof_binding_hash_from_payload(tampered) != proof_binding_hash_from_payload(stored)


def test_proof_binding_hash_uses_read_contract_raw_state_not_safe_export(tmp_path) -> None:
    from ces.verification.completion_contract import ProtectedSurface, _contract_storage_dict
    from ces.verification.proof_binding import proof_binding_hash, proof_binding_hash_from_payload

    contract = _contract(
        reality_boundary=RealityBoundaryContract(
            success_predicates=(SuccessPredicate(id="AC-001", text="original measurable outcome"),),
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="test",
                    command="uv run pytest tests/original.py -q",
                    cwd=".",
                ),
            ),
            protected_surfaces=(ProtectedSurface(path="tests/original.py", reason="must verify behavior"),),
            allowed_test_paths=("tests/original.py",),
            denied_test_paths=("tests/mutated.py",),
        ).with_predicate_hash()
    )
    stored = _contract_storage_dict(contract)
    assert proof_binding_hash(contract) == proof_binding_hash_from_payload(stored)

    tampered = json.loads(json.dumps(stored))
    tampered["reality_boundary"]["success_predicates"][0].pop("text")
    tampered["reality_boundary"]["official_evaluators"][0]["command"] = ""
    tampered["reality_boundary"]["official_evaluators"][0].pop("cwd")
    tampered["reality_boundary"]["protected_surfaces"][0].pop("path")
    tampered["reality_boundary"]["allowed_test_paths"] = []
    contract_path = tmp_path / "completion-contract.json"
    contract_path.write_text(json.dumps(tampered), encoding="utf-8")
    reloaded = CompletionContract.read(contract_path)

    assert proof_binding_hash(reloaded) != proof_binding_hash(contract)


def test_proof_binding_hash_changes_when_default_cwd_raw_field_is_removed_on_read_path(tmp_path) -> None:
    from ces.verification.completion_contract import _contract_storage_dict
    from ces.verification.proof_binding import proof_binding_hash

    contract = _contract(
        reality_boundary=RealityBoundaryContract(
            official_evaluators=(
                OfficialEvaluator(
                    id="VC-001",
                    command_id="VC-001",
                    kind="test",
                    command="uv run pytest tests/original.py -q",
                    cwd=".",
                ),
            ),
        ).with_predicate_hash()
    )
    tampered = json.loads(json.dumps(_contract_storage_dict(contract)))
    tampered["reality_boundary"]["official_evaluators"][0].pop("cwd")
    contract_path = tmp_path / "completion-contract.json"
    contract_path.write_text(json.dumps(tampered), encoding="utf-8")

    assert proof_binding_hash(CompletionContract.read(contract_path)) != proof_binding_hash(contract)
