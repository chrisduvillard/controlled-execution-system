# CES Recovery Half-Failure Fixes Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make CES recover cleanly when a builder runtime is interrupted halfway, without stale `running` sessions, confusing recovery mutations, stale active manifests, or `--project-root` gaps.

**Architecture:** Add a small builder-session reconciliation layer that converts stale `running` sessions into explicit blocked/retryable state before status/recovery decisions. Keep the recovery executor fail-closed behind the planner gate, and make continuation either reuse the existing manifest or supersede the stale one before creating a replacement. Finish with CLI consistency for `ces report builder --project-root` and a live replay against the saved recovery-gauntlet target.

**Tech Stack:** Python 3.13, Typer CLI, SQLite local store, CES builder session records, recovery planner/executor, pytest, ruff, mypy.

---

## Source dogfood findings

Evidence report: `/tmp/ces-recovery-gauntlet-20260504-213539/artifacts/CES_RECOVERY_GAUNTLET_REPORT.md`

Findings covered:

- **F1 High:** interrupted runtime leaves stale `running` / `in_flight` state with no recovery detection.
- **F2 Medium/High:** `recover --auto-evidence` mutates a non-blocked stale-running session into blocked and runs zero-command verification.
- **F3 High:** `ces continue` succeeds but creates a new manifest while leaving the interrupted manifest active/in-flight.
- **F4 Low:** `ces report builder` lacks `--project-root`.

## Working assumptions to validate during implementation

- Current `builder_sessions.updated_at` is enough to detect a stale `running` session in tests and during CLI invocation. Persisting a real PID/heartbeat can be a later enhancement unless tests prove updated-at is insufficient.
- For a stale interrupted session with no runtime evidence, the safest state is:
  - `stage="blocked"`
  - `next_action="retry_runtime"`
  - `last_action="runtime_interrupted"` or `"stale_runtime_detected"`
  - `recovery_reason="runtime_interrupted"`
  - `last_error` explaining that CES found a stale running session and recommending `ces continue`.
- `ces continue` may create a new manifest if the original manifest cannot be safely reused, but it must mark the previous in-flight manifest as terminal/superseded/cancelled first.
- Existing terminal states are filtered from active manifests by `src/ces/local_store/queries.py::fetch_active_manifests`, currently excluding `merged`, `deployed`, `expired`, `rejected`. If CES has no `cancelled`/`superseded` workflow enum, use `rejected` with clear session/audit context rather than inventing a new enum in this PR.

---

## Task 1: Add stale-running session detection tests for recovery planning

**Objective:** Prove `ces recover --dry-run` identifies stale interrupted runtime sessions as blocked/retryable instead of saying only `ces status`.

**Files:**
- Modify: `tests/unit/test_recovery/test_recovery_plan.py`
- Reference: `src/ces/recovery/planner.py`
- Reference: `src/ces/local_store/store.py`

**Step 1: Write failing test for stale running session**

Add a helper and test near the existing recovery plan tests:

```python
from datetime import datetime, timedelta, timezone


def _seed_running_session(tmp_path: Path) -> tuple[LocalProjectStore, Path, str]:
    project_root = tmp_path
    (project_root / ".ces").mkdir()
    store = LocalProjectStore(project_root / ".ces" / "state.db", project_id="proj")
    brief_id = store.save_builder_brief(
        request="Build MiniLog",
        project_mode="greenfield",
        constraints=[],
        acceptance_criteria=["CLI works"],
        must_not_break=[],
        open_questions={},
        manifest_id="M-stale",
    )
    session_id = store.save_builder_session(
        brief_id=brief_id,
        request="Build MiniLog",
        project_mode="greenfield",
        stage="running",
        next_action="review_evidence",
        last_action="execution_started",
        manifest_id="M-stale",
        runtime_manifest_id="M-stale",
    )
    # Force updated_at old enough to be stale without sleeping.
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with store._connect() as conn:  # test-only direct fixture setup
        conn.execute(
            "UPDATE builder_sessions SET updated_at = ? WHERE session_id = ?",
            (stale_at, session_id),
        )
    return store, project_root, session_id


def test_plan_treats_stale_running_session_as_interrupted_and_retryable(tmp_path: Path) -> None:
    store, project_root, session_id = _seed_running_session(tmp_path)

    plan = build_recovery_plan(project_root=project_root, local_store=store)

    assert plan.session_id == session_id
    assert plan.blocked is True
    assert plan.can_run_auto_evidence is False
    assert "stale" in plan.explanation.lower() or "interrupted" in plan.explanation.lower()
    assert "ces continue" in plan.next_commands
    assert "ces recover --auto-evidence" not in plan.next_commands
```

**Step 2: Run RED**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_plan.py::test_plan_treats_stale_running_session_as_interrupted_and_retryable -q
```

Expected: FAIL because `build_recovery_plan()` currently returns `blocked=False` and `next_commands=["ces status"]` for any non-completed non-blocked session.

**Step 3: Do not implement yet**

Commit after this task only if using strict TDD commits:

```bash
git add tests/unit/test_recovery/test_recovery_plan.py
git commit -m "test: cover stale running recovery planning"
```

---

## Task 2: Implement builder-session stale runtime reconciliation primitive

**Objective:** Add a small, testable helper that recognizes stale `running` sessions and updates them to a blocked/retryable state.

**Files:**
- Create: `src/ces/recovery/reconciler.py`
- Modify: `tests/unit/test_recovery/test_recovery_plan.py`
- Possibly modify: `src/ces/local_store/store.py` only if a public helper is needed

**Step 1: Write focused tests for the helper**

Create `tests/unit/test_recovery/test_recovery_reconciler.py` with tests for:

```python
def test_reconcile_marks_stale_running_session_blocked(tmp_path: Path) -> None:
    # seed stage="running", updated_at old, no runtime evidence
    # call reconcile_stale_builder_session(project_root, store, stale_after_seconds=60)
    # assert session.stage == "blocked"
    # assert session.next_action == "retry_runtime"
    # assert session.last_action == "runtime_interrupted"
    # assert session.recovery_reason == "runtime_interrupted"
    # assert "stale" or "interrupted" in session.last_error


def test_reconcile_leaves_fresh_running_session_unchanged(tmp_path: Path) -> None:
    # seed stage="running", updated_at now
    # call reconcile_stale_builder_session(..., stale_after_seconds=3600)
    # assert stage remains "running"


def test_reconcile_leaves_completed_session_unchanged(tmp_path: Path) -> None:
    # seed completed session
    # call helper
    # assert no mutation
```

**Step 2: Run RED**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_reconciler.py -q
```

Expected: FAIL because the module/helper does not exist.

**Step 3: Implement minimal helper**

Create `src/ces/recovery/reconciler.py`:

```python
"""Reconcile stale builder runtime sessions into actionable recovery state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BuilderSessionReconciliation:
    changed: bool
    session_id: str | None
    reason: str | None
    message: str | None


def reconcile_stale_builder_session(
    *,
    project_root: Path,
    local_store: Any,
    stale_after_seconds: int = 900,
) -> BuilderSessionReconciliation:
    del project_root  # reserved for future PID/heartbeat evidence lookup
    getter = getattr(local_store, "get_latest_builder_session", None)
    updater = getattr(local_store, "update_builder_session", None)
    if not callable(getter) or not callable(updater):
        return BuilderSessionReconciliation(False, None, None, None)

    session = getter()
    if session is None or getattr(session, "stage", None) != "running":
        return BuilderSessionReconciliation(False, getattr(session, "session_id", None), None, None)

    updated_at = _parse_datetime(getattr(session, "updated_at", None))
    if updated_at is None:
        return BuilderSessionReconciliation(False, session.session_id, None, None)

    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age < stale_after_seconds:
        return BuilderSessionReconciliation(False, session.session_id, None, None)

    message = (
        "CES found a stale running builder session whose runtime no longer appears active; "
        "run `ces continue` to retry the saved request."
    )
    updater(
        session.session_id,
        stage="blocked",
        next_action="retry_runtime",
        last_action="runtime_interrupted",
        recovery_reason="runtime_interrupted",
        last_error=message,
    )
    return BuilderSessionReconciliation(True, session.session_id, "runtime_interrupted", message)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
```

**Step 4: Run GREEN**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_reconciler.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ces/recovery/reconciler.py tests/unit/test_recovery/test_recovery_reconciler.py
git commit -m "fix: reconcile stale builder runtime sessions"
```

---

## Task 3: Wire reconciliation into recovery planning

**Objective:** Make `ces recover --dry-run` call the reconciliation primitive before planning, so stale `running` sessions become blocked/retryable.

**Files:**
- Modify: `src/ces/recovery/planner.py`
- Modify: `tests/unit/test_recovery/test_recovery_plan.py`

**Step 1: Run the Task 1 RED test again**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_plan.py::test_plan_treats_stale_running_session_as_interrupted_and_retryable -q
```

Expected before implementation: FAIL.

**Step 2: Implement minimal planner wiring**

At the top of `src/ces/recovery/planner.py` import:

```python
from ces.recovery.reconciler import reconcile_stale_builder_session
```

At the beginning of `build_recovery_plan()` before `_latest_session(local_store)`:

```python
reconciliation = reconcile_stale_builder_session(project_root=project_root, local_store=local_store)
session = _latest_session(local_store)
```

When the session is now blocked and `reconciliation.changed` is true, prefer an interruption-specific plan before auto-evidence logic:

```python
if blocked and reconciliation.changed:
    return RecoveryPlan(
        session_id=str(getattr(session, "session_id", "")),
        manifest_id=manifest_id,
        evidence_packet_id=evidence_packet_id,
        blocked=True,
        can_run_auto_evidence=False,
        can_auto_complete=False,
        contract_path=str(contract_path) if contract_exists else None,
        explanation=reconciliation.message or "Latest builder session was interrupted and is ready to retry.",
        next_commands=("ces continue", "ces status"),
    )
```

**Important:** Do not suggest `ces recover --auto-evidence` for stale interrupted runs with no product evidence yet. The next action is retry/continue, not verification.

**Step 3: Run GREEN**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_plan.py -q
```

Expected: all recovery-plan tests pass.

**Step 4: Commit**

```bash
git add src/ces/recovery/planner.py tests/unit/test_recovery/test_recovery_plan.py
git commit -m "fix: plan interrupted builder recovery"
```

---

## Task 4: Make `recover --auto-evidence` honor the recovery planner gate

**Objective:** Prevent `run_auto_evidence_recovery()` from mutating non-blocked or non-verifiable sessions.

**Files:**
- Modify: `tests/unit/test_recovery/test_recovery_executor.py`
- Modify: `tests/unit/test_cli/test_recover_cmd.py`
- Modify: `src/ces/recovery/executor.py`
- Modify: `src/ces/cli/recover_cmd.py` only if user-facing JSON/text needs a new non-mutating result shape

**Step 1: Write failing executor test**

In `tests/unit/test_recovery/test_recovery_executor.py`, add:

```python
def test_auto_evidence_refuses_non_blocked_session_without_mutation(tmp_path: Path) -> None:
    store, project_root = _seed_project(tmp_path)
    session = store.get_latest_builder_session()
    assert session is not None
    store.update_builder_session(
        session.session_id,
        stage="running",
        next_action="review_evidence",
        last_action="execution_started",
        recovery_reason=None,
        last_error=None,
    )
    _write_passing_contract(project_root)
    before = store.get_latest_builder_session()

    result = run_auto_evidence_recovery(project_root=project_root, local_store=store, auto_complete=True)

    assert result.completed is False
    assert result.new_evidence_packet_id is None
    assert result.next_action in {"status", "run_continue"}
    assert "not blocked" in result.message.lower() or "cannot run" in result.message.lower()
    assert store.get_latest_builder_session() == before
```

**Step 2: Write CLI-level JSON test**

In `tests/unit/test_cli/test_recover_cmd.py`, add a fixture for non-blocked running session and assert:

```python
result = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete", "--json"])
assert result.exit_code == 0
payload = json.loads(result.stdout)
assert payload["result"]["completed"] is False
assert payload["result"]["new_evidence_packet_id"] is None
assert "not blocked" in payload["result"]["message"].lower()
```

**Step 3: Run RED**

```bash
uv run pytest \
  tests/unit/test_recovery/test_recovery_executor.py::test_auto_evidence_refuses_non_blocked_session_without_mutation \
  tests/unit/test_cli/test_recover_cmd.py -q
```

Expected: FAIL because executor currently only checks for session/contract and then runs verification/mutates failed sessions.

**Step 4: Implement guard in `src/ces/recovery/executor.py`**

Immediately after building `plan` and checking `plan.session_id`:

```python
if not plan.blocked or not plan.can_run_auto_evidence:
    return RecoveryExecutionResult(
        verification=VerificationRunResult(passed=False, commands=()),
        completed=False,
        dry_run=dry_run,
        new_evidence_packet_id=None,
        manifest_id=plan.manifest_id,
        session_id=plan.session_id,
        next_action="run_continue" if "ces continue" in plan.next_commands else "status",
        message=plan.explanation,
    )
```

If `VerificationRunResult` requires a different constructor shape, inspect `src/ces/verification/runner.py` and adapt.

Also guard empty command verification after refresh:

```python
if not contract.inferred_commands:
    return RecoveryExecutionResult(
        verification=VerificationRunResult(passed=False, commands=()),
        completed=False,
        dry_run=dry_run,
        new_evidence_packet_id=None,
        manifest_id=plan.manifest_id,
        session_id=plan.session_id,
        next_action="run_continue",
        message="No verification commands are available yet; run `ces continue` to retry the builder session.",
    )
```

Do not call `_update_session()` in either guard path.

**Step 5: Run GREEN**

```bash
uv run pytest tests/unit/test_recovery/test_recovery_executor.py tests/unit/test_cli/test_recover_cmd.py -q
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/ces/recovery/executor.py tests/unit/test_recovery/test_recovery_executor.py tests/unit/test_cli/test_recover_cmd.py
git commit -m "fix: keep recovery auto-evidence behind planner gate"
```

---

## Task 5: Fix continuation so stale manifests do not remain active

**Objective:** Ensure `ces continue` after an interrupted session does not leave the original in-flight manifest listed in `active_manifests` once the replacement run completes.

**Files:**
- Modify: `tests/unit/test_cli/test_run_cmd.py`
- Modify: `src/ces/cli/run_cmd.py`
- Possibly modify: `src/ces/local_store/store.py` for a helper to terminalize manifests by id

**Step 1: Identify existing `continue_task` tests and helpers**

Search locally:

```bash
uv run pytest tests/unit/test_cli/test_run_cmd.py -q
```

Read the existing fake service patterns in `tests/unit/test_cli/test_run_cmd.py` before adding any test. Do not invent a new fake factory if the file already has one.

**Step 2: Write failing test at service/helper level if CLI full-flow setup is too heavy**

Preferred behavioral test:

```python
def test_continue_after_interrupted_session_terminalizes_previous_manifest(...):
    # Seed a builder session stage="blocked", recovery_reason="runtime_interrupted",
    # manifest_id/runtime_manifest_id="M-old".
    # Seed manifest M-old workflow_state="in_flight".
    # Run continue_task via CliRunner with a fake runtime that returns a valid completion claim.
    # Assert latest builder session is completed/merged.
    # Assert M-old workflow_state is terminal and fetch_active_manifests does not include M-old.
```

If a full CLI test is too expensive, extract a small helper first under TDD:

- New helper in `src/ces/cli/run_cmd.py`:

```python
def _should_supersede_previous_manifest(current_session: Any, new_manifest_id: str) -> str | None:
    previous = getattr(current_session, "runtime_manifest_id", None) or getattr(current_session, "manifest_id", None)
    if not previous or previous == new_manifest_id:
        return None
    if getattr(current_session, "recovery_reason", None) == "runtime_interrupted":
        return str(previous)
    if getattr(current_session, "last_action", None) in {"runtime_interrupted", "stale_runtime_detected"}:
        return str(previous)
    return None
```

Test this helper, then add one integration-ish test around manifest terminalization.

**Step 3: Run RED**

```bash
uv run pytest tests/unit/test_cli/test_run_cmd.py::test_continue_after_interrupted_session_terminalizes_previous_manifest -q
```

Expected: FAIL because `continue` currently creates `M-new` and does not terminalize `M-old`.

**Step 4: Implement minimal manifest terminalization**

In `_run_brief_flow()`, capture the previous manifest before creating/saving a new one:

```python
previous_runtime_manifest_id = (
    getattr(current_session, "runtime_manifest_id", None)
    or getattr(current_session, "manifest_id", None)
    if current_session is not None
    else None
)
```

After the new manifest is approved/merged successfully, before final session update or immediately after saving the merged new manifest:

```python
previous_to_supersede = _should_supersede_previous_manifest(current_session, manifest.manifest_id)
if approved and not merge_blocked and previous_to_supersede:
    previous_manifest = local_store.get_manifest_row(previous_to_supersede)
    if previous_manifest is not None and previous_manifest.workflow_state not in {"merged", "deployed", "expired", "rejected"}:
        # Reconstruct via ManifestManager if possible, otherwise add a local-store helper.
        previous_task_manifest = await manager.get_manifest(previous_to_supersede)  # verify actual API name
        if previous_task_manifest is not None:
            previous_task_manifest = _with_workflow_state(previous_task_manifest, WorkflowState.REJECTED)
            await manager.save_manifest(previous_task_manifest)
```

If `ManifestManager` lacks `get_manifest`, use `local_store.get_manifest_row()` plus existing manager row conversion patterns, or add a narrow `local_store.update_manifest_workflow_state(manifest_id, workflow_state)` helper with unit tests.

**Important:** Do not blindly reject old manifests for normal `ces continue` review flows. Only terminalize old active manifests when the current session has `recovery_reason="runtime_interrupted"` / `last_action="runtime_interrupted"` and the new manifest id differs.

**Step 5: Add status invariant test**

Add a test that builds a local store with:

- old manifest `M-old` in `in_flight`
- latest builder session completed on `M-new`

Then call the new helper/reconciliation function and assert active manifests excludes `M-old` after continuation completion.

**Step 6: Run GREEN**

```bash
uv run pytest tests/unit/test_cli/test_run_cmd.py -q
```

Expected: PASS.

**Step 7: Commit**

```bash
git add src/ces/cli/run_cmd.py tests/unit/test_cli/test_run_cmd.py src/ces/local_store/store.py src/ces/local_store/writes.py
# include only files actually changed
git commit -m "fix: supersede interrupted manifests on continue"
```

---

## Task 6: Add `--project-root` to `ces report builder`

**Objective:** Make historical builder report export usable from source-checkout/operator contexts, matching `status`, `review`, and `recover`.

**Files:**
- Modify: `tests/unit/test_cli/test_builder_report_cmd.py`
- Modify: `src/ces/cli/report_cmd.py`

**Step 1: Write failing CLI test**

In `tests/unit/test_cli/test_builder_report_cmd.py`, add:

```python
def test_report_builder_accepts_project_root(tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    ces_dir = project / ".ces"
    ces_dir.mkdir()
    (ces_dir / "config.yaml").write_text("project_id: local-proj\npreferred_runtime: codex\n", encoding="utf-8")

    mock_store = MagicMock()
    mock_store.get_latest_builder_session_snapshot.return_value = SimpleNamespace(
        request="Build MiniLog",
        project_mode="greenfield",
        stage="completed",
        next_action="start_new_session",
        next_step="Start a new task",
        latest_activity="CES recorded approval",
        latest_artifact="approval",
        brief_only_fallback=False,
        brief=SimpleNamespace(prl_draft_path=None),
        manifest=SimpleNamespace(manifest_id="M-123", workflow_state="merged"),
        runtime_execution=SimpleNamespace(exit_code=0, reported_model="gpt-5.5"),
        evidence={"packet_id": "EP-123", "triage_color": "green"},
        approval=SimpleNamespace(decision="approve"),
        session=SimpleNamespace(session_id="BS-123"),
        brownfield=None,
    )

    with _patch_services({"local_store": mock_store}):
        result = runner.invoke(_get_app(), ["report", "builder", "--project-root", str(project), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["builder_run"]["request"] == "Build MiniLog"
    assert (project / ".ces" / "exports" / "builder-run-report-bs-123.md").is_file()
```

**Step 2: Run RED**

```bash
uv run pytest tests/unit/test_cli/test_builder_report_cmd.py::test_report_builder_accepts_project_root -q
```

Expected: FAIL with `No such option: --project-root`.

**Step 3: Implement option**

In `src/ces/cli/report_cmd.py`, add:

```python
project_root: Path | None = typer.Option(
    None,
    "--project-root",
    help="CES project root to report on; defaults to cwd/.ces discovery.",
),
```

Then resolve:

```python
resolved_project_root = find_project_root(project_root) if project_root is not None else find_project_root()
resolved_output_dir = output_dir if output_dir.is_absolute() else resolved_project_root / output_dir
async with get_services(project_root=resolved_project_root) as services:
    ...
```

Check `get_services` signature in `src/ces/cli/_factory.py`; if it uses `project_root` positional/keyword differently, follow existing commands such as `status_cmd.py`, `review_cmd.py`, or `recover_cmd.py`.

**Step 4: Run GREEN**

```bash
uv run pytest tests/unit/test_cli/test_builder_report_cmd.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/ces/cli/report_cmd.py tests/unit/test_cli/test_builder_report_cmd.py
git commit -m "fix: add project-root to builder reports"
```

---

## Task 7: Add CLI/status regression coverage for the exact recovery-gauntlet user journey

**Objective:** Prove the fixed behavior end-to-end at the unit/CLI level without invoking Codex.

**Files:**
- Create or modify: `tests/unit/test_cli/test_recovery_half_failure_flow.py`
- Reuse: `LocalProjectStore`, `CliRunner`, fake services where needed

**Step 1: Write scenario test**

Create a test that models the observed state transitions:

1. Seed target `.ces` with session stage `running`, manifest `M-old` in `in_flight`, and an empty pre-runtime completion contract.
2. Force `updated_at` old.
3. Invoke `ces recover --dry-run --json --project-root <target>`.
4. Assert JSON plan says blocked/retryable and recommends `ces continue`, not auto-evidence.
5. Invoke `ces recover --auto-evidence --auto-complete --json --project-root <target>`.
6. Assert it does **not** run zero-command verification, does **not** write evidence, and returns a non-mutating retry/continue message.

Pseudocode:

```python
def test_interrupted_runtime_recovery_flow_is_actionable_without_zero_command_verification(tmp_path, monkeypatch):
    project = seed_interrupted_project(tmp_path)

    dry = runner.invoke(_get_app(), ["recover", "--dry-run", "--json", "--project-root", str(project)])
    assert dry.exit_code == 0
    dry_payload = json.loads(dry.stdout)
    assert dry_payload["plan"]["blocked"] is True
    assert "ces continue" in dry_payload["plan"]["next_commands"]
    assert "ces recover --auto-evidence" not in dry_payload["plan"]["next_commands"]

    auto = runner.invoke(_get_app(), ["recover", "--auto-evidence", "--auto-complete", "--json", "--project-root", str(project)])
    assert auto.exit_code == 0
    auto_payload = json.loads(auto.stdout)
    assert auto_payload["result"]["new_evidence_packet_id"] is None
    assert auto_payload["result"]["verification"]["commands"] == []
    assert auto_payload["result"]["next_action"] == "run_continue"
```

**Step 2: Run RED, then GREEN after Tasks 2-4**

```bash
uv run pytest tests/unit/test_cli/test_recovery_half_failure_flow.py -q
```

Expected after previous tasks: PASS.

**Step 3: Commit**

```bash
git add tests/unit/test_cli/test_recovery_half_failure_flow.py
git commit -m "test: cover interrupted runtime recovery flow"
```

---

## Task 8: Documentation update for interrupted builder recovery

**Objective:** Teach operators the fixed recovery path and prevent confusion around stale runtime sessions.

**Files:**
- Modify: `docs/Operator_Playbook.md`
- Modify: `docs/Troubleshooting.md`
- Possibly modify: `docs/Quick_Reference_Card.md`

**Step 1: Add docs test first**

Add or update doc tests under `tests/unit/test_docs/` to assert the docs mention:

- `ces recover --dry-run`
- `ces continue`
- interrupted/stale runtime session language
- `ces report builder --project-root`

Example:

```python
def test_operator_docs_cover_interrupted_runtime_recovery() -> None:
    text = Path("docs/Operator_Playbook.md").read_text(encoding="utf-8")
    assert "interrupted" in text.lower() or "stale runtime" in text.lower()
    assert "ces recover --dry-run" in text
    assert "ces continue" in text
    assert "ces report builder --project-root" in text
```

**Step 2: Run RED**

```bash
uv run pytest tests/unit/test_docs/test_operator_playbook_docs.py -q
```

Expected: FAIL until docs are updated.

**Step 3: Update docs**

Add a concise section:

```markdown
### Interrupted runtime or closed terminal

If a `ces build` terminal is killed while Codex/Claude is running:

1. Run `ces recover --dry-run --project-root /path/to/repo`.
2. If CES reports an interrupted/stale runtime session, run `ces continue --project-root /path/to/repo ...` or rerun from the project root.
3. After completion, export evidence with `ces report builder --project-root /path/to/repo`.
4. Do not use `recover --auto-evidence` until CES says verification evidence can be rerun.
```

**Step 4: Run GREEN**

```bash
uv run pytest tests/unit/test_docs/test_operator_playbook_docs.py tests/unit/test_docs/test_quick_reference_card_docs.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add docs/Operator_Playbook.md docs/Troubleshooting.md docs/Quick_Reference_Card.md tests/unit/test_docs/
git commit -m "docs: explain interrupted builder recovery"
```

---

## Task 9: Live spot check against the original recovery-gauntlet target

**Objective:** Verify the source checkout fix corrects the exact saved dogfood target behavior, not just unit tests.

**Files:**
- No source files unless a finding remains open.
- Evidence paths under `/tmp/ces-recovery-gauntlet-20260504-213539/artifacts/`.

**Step 1: Preserve original state**

The original target has already moved past the interrupted state. Do **not** mutate it blindly. Copy it first:

```bash
SRC=/tmp/ces-recovery-gauntlet-20260504-213539/target
REPRO=/tmp/ces-recovery-gauntlet-replay-$(date +%Y%m%d-%H%M%S)
cp -a "$SRC" "$REPRO"
```

**Step 2: Reset replay DB to interrupted shape**

Use a small Python script against `$REPRO/.ces/state.db` to:

- set builder session `BS-f7e73b34f4db` or latest session to `stage='running'`, `next_action='review_evidence'`, `last_action='execution_started'`, `recovery_reason=NULL`, `last_error=NULL`, old `updated_at`.
- set old manifest `M-f4f7d71daf17` to `workflow_state='in_flight'` if present.
- ensure `.ces/completion-contract.json` remains empty/unknown as in the original interruption.

Save the script output to the artifacts directory.

**Step 3: Run source-checkout CLI spot checks**

From CES repo:

```bash
CES=/home/chris/.Hermes/workspace/controlled-execution-system/.venv/bin/ces
REPRO=/tmp/ces-recovery-gauntlet-replay-...

"$CES" recover --project-root "$REPRO" --dry-run --json \
  > /tmp/ces-recovery-gauntlet-20260504-213539/artifacts/source-replay-recover-dry-run.json

"$CES" recover --project-root "$REPRO" --auto-evidence --auto-complete --json \
  > /tmp/ces-recovery-gauntlet-20260504-213539/artifacts/source-replay-recover-auto.json

"$CES" status --project-root "$REPRO" --json \
  > /tmp/ces-recovery-gauntlet-20260504-213539/artifacts/source-replay-status.json
```

**Expected:**

- Dry-run recommends `ces continue` and does not suggest auto-evidence.
- Auto-evidence does not mutate into `fix_verification` / zero-command failed verification.
- Status shows blocked/retryable interrupted runtime, not stale running.

**Step 4: Optional continuation spot check**

Only if Codex runtime is available and Chris has approved side effects for this target:

```bash
"$CES" continue --runtime codex --yes --accept-runtime-side-effects --full
"$CES" status --project-root "$REPRO" --json > .../source-replay-status-after-continue.json
```

Expected: completed/approved/merged latest builder session and no stale old in-flight manifest in `active_manifests`.

**Step 5: Commit nothing**

This task produces PR evidence, not source changes.

---

## Task 10: Full verification package and PR body

**Objective:** Prove the fix set is safe and map every dogfood finding to a test/fix.

**Commands:**

```bash
git diff --check
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/unit/test_recovery tests/unit/test_cli/test_recover_cmd.py tests/unit/test_cli/test_run_cmd.py tests/unit/test_cli/test_builder_report_cmd.py -q
uv run pytest tests/unit -q
uv run pytest -q --cov=ces --cov-report=term-missing --cov-fail-under=80
uv build
uv run twine check dist/*
uv run pip-audit --strict
```

**Expected:**

- No diff whitespace errors.
- Ruff/mypy pass.
- Targeted and full unit suites pass.
- Coverage remains above threshold.
- Build/twine/audit pass.

**PR body must include:**

- Finding map:
  - F1 -> stale runtime reconciliation in status/recover planning + tests.
  - F2 -> planner gate in auto-evidence executor + zero-command guard + tests.
  - F3 -> interrupted manifest supersession on continue + status invariant test.
  - F4 -> `ces report builder --project-root` + CLI test.
- Live replay evidence paths.
- Exact validation commands and pass counts.
- Risk note: stale detection currently uses `updated_at`; PID/heartbeat persistence remains optional future hardening unless implemented in this PR.

---

## Definition of Done

- `ces recover --dry-run` on a stale interrupted running session reports a blocked/retryable interrupted runtime and recommends `ces continue`.
- `ces recover --auto-evidence --auto-complete` does not mutate sessions when planner says auto-evidence cannot run.
- Empty inferred verification commands are not treated as product verification failure for interrupted/no-product sessions.
- `ces continue` after an interrupted session does not leave the old manifest active/in-flight after the replacement run completes.
- `ces report builder --project-root <target>` works and exports under the target `.ces/exports` by default.
- Docs explain interrupted runtime recovery.
- Targeted tests, full unit suite, lint, format, typecheck, build, metadata check, audit, and source-checkout live replay pass.

## Sequencing recommendation

Implement as **one PR** if the diff stays small and coherent. If Task 5 grows large, split into two sequential PRs:

1. PR A: stale recovery planner/executor + report `--project-root`.
2. PR B: continuation manifest supersession + live replay.

Do not claim the recovery-gauntlet wave is closed until Task 9 live replay passes against a copied/reconstructed target state.
