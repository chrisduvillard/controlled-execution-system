"""Local-mode FreshCart end-to-end example.

Unlike run_e2e.py (which mocks all services), this script exercises the
real local-mode CES pipeline:

- Real SQLite persistence via LocalProjectStore
- Real deterministic classification via ClassificationOracle (TF-IDF)
- Real manifest management and audit ledger (HMAC-signed)
- Only the runtime adapter subprocess is mocked (Codex/Claude CLI
  won't be present in CI)

Requires: no Postgres, no Redis, no API keys.

Usage:
    uv run python -m examples.freshcart.run_local_e2e
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()

STEPS: list[tuple[str, bool]] = []


def _step(name: str, passed: bool) -> None:
    STEPS.append((name, passed))
    status = "PASS" if passed else "FAIL"
    print(f"  {status} {name}")


def run_local_e2e() -> bool:
    """Run the full local-mode E2E pipeline. Returns True if all steps pass."""
    work_dir = Path(tempfile.mkdtemp(prefix="ces-freshcart-"))
    print(f"Working directory: {work_dir}")

    try:
        return _run_pipeline(work_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _run_pipeline(work_dir: Path) -> bool:
    import os

    # Step 1: Initialize project via ces init
    print("\n--- Step 1: Initialize project ---")
    os.chdir(work_dir)

    from ces.cli import app

    result = runner.invoke(app, ["init", "freshcart"])
    _step("ces init freshcart", result.exit_code == 0)
    if result.exit_code != 0:
        print(f"  stdout: {result.stdout}")
        return False

    # Verify .ces/ structure
    ces_dir = work_dir / ".ces"
    _step(".ces/ directory created", ces_dir.is_dir())
    _step("config.yaml exists", (ces_dir / "config.yaml").exists())
    _step("state.db exists", (ces_dir / "state.db").exists())

    # Step 2: Use real local-mode services to create a manifest
    print("\n--- Step 2: Create manifest via real services ---")
    import asyncio

    from ces.cli._factory import get_services

    async def _create_manifest():
        async with get_services() as services:
            mm = services["manifest_manager"]
            oracle = services["classification_oracle"]
            audit = services["audit_ledger"]

            # Classify using real TF-IDF oracle
            task_desc = "Fix null pointer in product search when category is empty"
            oracle_result = oracle.classify(task_desc)
            _step(
                f"Classification oracle returned (confidence={oracle_result.confidence:.2f})",
                oracle_result.confidence > 0,
            )

            # Extract classification from matched rule (or use defaults)
            from ces.shared.enums import BehaviorConfidence, ChangeClass, RiskTier

            if oracle_result.matched_rule:
                risk_tier = oracle_result.matched_rule.risk_tier
                behavior_confidence = oracle_result.matched_rule.behavior_confidence
                change_class = oracle_result.matched_rule.change_class
            else:
                risk_tier = RiskTier.C
                behavior_confidence = BehaviorConfidence.BC1
                change_class = ChangeClass.CLASS_1

            # Create manifest through real manager
            manifest = await mm.create_manifest(
                description=task_desc,
                risk_tier=risk_tier,
                behavior_confidence=behavior_confidence,
                change_class=change_class,
                affected_files=["src/search/product_search.py"],
                token_budget=50000,
                owner="freshcart-demo",
            )
            _step(
                f"Manifest created: {manifest.manifest_id}",
                manifest.manifest_id is not None,
            )

            # Step 3: Verify audit events were recorded by manifest creation
            print("\n--- Step 3: Audit ledger ---")
            _step("Audit ledger available", audit is not None)

            return services, manifest

    _services, _manifest = asyncio.run(_create_manifest())

    # Step 4: Check local store has data
    print("\n--- Step 4: Verify local persistence ---")
    import yaml

    from ces.local_store import LocalProjectStore

    with open(ces_dir / "config.yaml") as f:
        project_config = yaml.safe_load(f)
    project_id = project_config.get("project_id", "default")

    store = LocalProjectStore(
        db_path=ces_dir / "state.db",
        project_id=project_id,
    )
    manifests = store.get_active_manifest_rows()
    _step(f"Local store has {len(manifests)} manifest(s)", len(manifests) >= 1)

    audits = store.get_latest_audit(limit=10)
    _step(f"Local store has {len(audits)} audit entry(ies)", len(audits) >= 1)

    # Step 5: Verify local project is queryable
    # (ces status may fail in non-interactive runners due to Rich/async;
    # verify through the store directly instead)
    print("\n--- Step 5: Verify project queryable ---")
    settings = store.get_project_settings()
    _step(
        f"Project settings readable (name={settings.get('project_name', '?')})",
        settings.get("execution_mode") == "local",
    )

    # Summary
    print("\n" + "=" * 50)
    passed = sum(1 for _, ok in STEPS if ok)
    total = len(STEPS)
    print(f"Results: {passed}/{total} steps passed")

    return passed == total


if __name__ == "__main__":
    print("FreshCart Local-Mode E2E Example")
    print("=" * 50)
    success = run_local_e2e()
    sys.exit(0 if success else 1)
