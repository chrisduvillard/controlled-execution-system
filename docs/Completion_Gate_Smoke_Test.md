# Completion Gate — Smoke-Test Runbook

## Purpose

The Completion Gate (workflow state `verifying` + `CompletionVerifier` +
auto-repair loop) shipped without ever meeting a real LLM. Every test in the
suite uses `MagicMock` runtimes and a `_ScriptedRuntime` that returns canned
stdout. This runbook is the procedure to prove the gate works against an
actual `claude -p` or `codex` invocation.

Run this once after any change that touches:

- `_build_prompt_pack()` in `src/ces/cli/execute_cmd.py`
- `parse_completion_claim()` in `src/ces/execution/completion_parser.py`
- The Completion Gate prompt schema
- Any runtime adapter

## Pre-requisites

- `ces` CLI on `$PATH` (`uv run ces --help` is fine).
- `claude` or `codex` CLI installed (`which claude && which codex`).
- A scratch project directory; **do not run this against real work** — the
  agent will modify files according to its task.

## Procedure

### 1. Bootstrap a scratch project

```bash
mkdir /tmp/ces-smoke && cd /tmp/ces-smoke
git init
echo '# scratch' > README.md
git add README.md && git commit -m "init"
ces init                       # creates .ces/ + keys + state.db
```

### 2. Plant a tiny task that the gate can verify

Create a deliberately failing test the agent must fix:

```bash
mkdir tests
cat > tests/test_smoke.py <<'PY'
def test_known_failure() -> None:
    assert 1 + 1 == 3
PY
```

The agent's job: make the test pass.

### 3. Author a manifest opted into the gate

```bash
ces manifest "Fix tests/test_smoke.py so the test passes" \
  --yes \
  --acceptance-criterion "tests/test_smoke.py passes" \
  --acceptance-criterion "no new test added" \
  --verification-sensor test_pass
```

Capture the printed `manifest_id` (e.g., `M-abc123…`). Confirm the saved
panel shows `verification_sensors: ['test_pass']` rather than the legacy
marker.

### 4. Run the gate with auto-repair

```bash
ces execute M-abc123... --runtime claude --auto-repair 2
```

Expected sequence:

1. `_build_prompt_pack` injects the Completion Gate instructions plus the
   two acceptance criteria into the prompt.
2. `claude -p` runs, produces a fix, and (the unproven part) emits a
   `ces:completion` block listing files_changed and criteria_satisfied.
3. The agent must also write a JSON pytest report at `pytest-results.json`
   (the convention `TestPassSensor` reads). If the agent doesn't produce
   the artifact, the sensor skips and the gate passes vacuously — that's
   itself diagnostic: the prompt needs to instruct the agent to run pytest
   with `--json-report --json-report-file=pytest-results.json` (which
   requires the `pytest-json-report` plugin).
4. `CompletionVerifier` runs:
   - schema check against the claim,
   - criterion check against `acceptance_criteria`,
   - scope check against `affected_files`,
   - `TestPassSensor` against the artifact.
5. On pass: manifest advances to `under_review`, exit 0.
6. On fail: repair prompt is fed back, agent retries, re-verify.

### 5. Capture the run

For each smoke run, record in `docs/Completion_Gate_Smoke_Notes.md`:

- The exact `ces:completion` block the model emitted (verbatim).
- Whether the regex `_BLOCK_RE` in `completion_parser.py` matched it.
- Which acceptance criteria the model addressed vs. skipped.
- Whether the agent produced `pytest-results.json` unprompted.
- The `--json` output of the run (if you ran with `--json`).
- Any panic / unhandled exception path — those are bugs.

## Likely first-run failure modes (and what they tell us)

| Symptom | Diagnosis | Fix lives in |
|---------|-----------|--------------|
| "Agent did not emit a ces:completion block" on every run | Prompt schema is too implicit; model didn't notice the requirement | `_COMPLETION_CLAIM_INSTRUCTIONS` in `src/ces/cli/execute_cmd.py` |
| Block emitted but JSON has wrong keys / missing fields | Schema is fine but model is paraphrasing | Tighten the prompt's "rules" section; include a literal example |
| Block parsed, but `criteria_satisfied` list empty | Model didn't realise it must address every criterion | Add a sentence "you MUST emit one entry per acceptance criterion" |
| Block parsed; verifier rejects with `criterion_unaddressed` | The model addressed criteria but with different wording | Either loosen the matching (semantic) or instruct the model to copy criterion text verbatim |
| `TestPassSensor` skipped because no `pytest-results.json` | Model didn't run pytest with the right flag | Mention the artifact filename + plugin in the prompt |
| Auto-repair loops forever, same claim each time | `detect_no_progress` should be tripping; verify N4 wiring | `src/ces/cli/execute_cmd.py` claim-signature capture |

## Out-of-scope for the smoke test

- **Performance / token cost.** First-run is exploratory; don't optimise yet.
- **Multi-language repos.** Use a Python-only scratch dir; `pytest-results.json` is the only artifact wired today.
- **Real merge.** Don't `--approve`; the gate just needs to reach `under_review`.

## Success criteria for marking N1 complete

After at least one smoke run that produces:

- A passing case (gate green, manifest in `under_review`),
- A failing case (gate red, repair prompt visible, retry observed),
- A notes file with verbatim agent output for each.

The smoke test is "complete" when those three artifacts exist. It does not
need to be automated — manual exploration is the point.
