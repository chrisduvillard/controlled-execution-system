# AI-Assisted Coding Risk Mitigation Implementation Plan

Date: 2026-05-01

This plan turns the CES AI-assisted coding risk assessment into trackable product
and code changes. The implementation should preserve CES as a local-first,
builder-first governance CLI while making missing evidence, runtime side effects,
and weak verification harder to miss.

## Goals

- Treat missing evidence as a blocking governance signal, not as success.
- Require agents to show repo exploration and command-backed verification before
  completion can pass.
- Make runtime side-effect boundaries explicit before unattended approval.
- Improve security, dependency, version, documentation, ownership, and review
  signals without introducing a hosted control plane.
- Keep expert workflow opt-outs possible, but explicit and auditable.

## Non-Goals

- Do not add a hosted or service-first runtime path.
- Do not replace local Codex or Claude runtime credentials.
- Do not claim semantic proof of correctness. CES should expose stronger
  evidence and blockers, not pretend it can prove arbitrary code correct.
- Do not add broad framework rewrites while implementing these controls.

## Milestone 1: Completion Evidence Becomes Enforced

CES should reject completion claims that do not prove the agent explored the real
repo and ran concrete verification commands when the manifest requires those
facts.

Implementation notes:

- Extend `CompletionClaim` with `exploration_evidence` and
  `verification_commands`.
- Extend `TaskManifest` with evidence policy flags:
  `requires_exploration_evidence`, `requires_verification_commands`,
  `requires_impacted_flow_evidence`, and `accepted_runtime_side_effect_risk`.
- Update prompt instructions so runtime agents know the required fields.
- Update `CompletionVerifier` to block missing exploration evidence, missing
  command evidence, failed verification commands, and unresolved open questions.

TODO:

- [x] Add model fields for exploration and verification command evidence.
- [x] Add manifest policy fields for evidence requirements.
- [x] Add verifier checks for missing required evidence.
- [x] Add verifier check for unresolved open questions.
- [x] Update completion prompt schema and rules.
- [x] Add artifact-path existence checks for verification command artifacts.
- [x] Add impacted-flow evidence checks for brownfield manifests.

## Milestone 2: Missing Artifacts Are Blocking

Configured deterministic sensors should fail when their required artifacts are
absent. A configured sensor without data is not a passing verification.

Implementation notes:

- Change completion-gate sensors so missing `pytest-results.json`,
  `ruff-report.json`, and `mypy-report.txt` return failed `SensorResult`s with
  `missing_artifact` findings.
- Change coverage sensor so missing `coverage.json` fails when the sensor runs.
- Align coverage pass threshold with the repo/product 90% coverage gate.

TODO:

- [x] Make missing pytest artifact fail.
- [x] Make missing ruff artifact fail.
- [x] Make missing mypy artifact fail.
- [x] Make missing coverage artifact fail.
- [x] Raise coverage sensor pass threshold from 60% to 90%.
- [x] Add JSON report generation guidance to repair prompts.
- [x] Update CLI docs and troubleshooting examples for artifact-producing commands.

## Milestone 3: Builder Manifests Default To Stronger Evidence

The builder-first flow should create manifests that opt into core verification
and evidence requirements by default.

Implementation notes:

- Builder-created manifests should default to `test_pass`, `lint`, `typecheck`,
  and `coverage` verification sensors.
- Builder-created manifests should require exploration evidence and verification
  commands.
- Brownfield builder manifests should require impacted-flow evidence.
- Expert manifests may still opt out, but empty sensors should remain visible in
  evidence and reports.

TODO:

- [x] Add default builder completion sensors.
- [x] Pass exploration and verification requirements to builder manifests.
- [x] Mark brownfield builder manifests as impacted-flow-evidence required.
- [x] Add explicit expert workflow warning when `verification_sensors=()`.
- [x] Add tests for brownfield impacted-flow manifest policy.
- [x] Add explain/report output for empty-sensor opt-outs.

## Milestone 4: Runtime Side Effects Require Explicit Acceptance

CES should not silently auto-approve unattended Codex runs when CES cannot
enforce manifest tool allowlists through the adapter.

Implementation notes:

- Keep runtime safety disclosure in evidence packets.
- Add a side-effect auto-approval blocker for workspace-scoped runtimes whose
  tool allowlist is not enforced.
- Add `--accept-runtime-side-effects` for operators who intentionally accept that
  boundary in unattended runs.
- Do not block interactive/manual approval solely for this reason; surface it as
  evidence.

TODO:

- [x] Add runtime side-effect policy helper.
- [x] Add `--accept-runtime-side-effects` to builder and continue flows.
- [x] Add unattended auto-approval blocker for non-enforced tool allowlists.
- [x] Add decisioning output that names accepted runtime side-effect waivers.
- [x] Add report output for runtime side-effect boundary and waiver state.
- [x] Add end-to-end CLI test for waiver versus blocker behavior.

## Milestone 5: API, Version, And Dependency Grounding

CES should make hallucinated APIs, dependency bloat, and version drift more
visible and harder to approve accidentally.

Implementation notes:

- Keep dependency-change evidence mandatory for dependency file changes.
- Add `pip-audit` artifact parsing as a deterministic sensor.
- Add dependency freshness/version compatibility checks to `ces doctor`.
- Wire manifest `mcp_servers` into runtime prompt or adapter configuration when
  supported. If unsupported by a runtime, disclose that limitation.

TODO:

- [x] Preserve dependency-change evidence enforcement.
- [x] Add `pip-audit` artifact sensor.
- [x] Add dependency freshness sensor or doctor check.
- [x] Add `ces doctor --runtime-safety` version/adapter report.
- [x] Wire supported MCP grounding into runtime adapters.
- [x] Disclose unsupported MCP grounding per runtime.

## Milestone 6: Security, Privacy, And Prompt-Injection Hardening

CES already has env allowlisting and secret scrubbing, but it should scan likely
runtime context before invocation and apply untrusted-content framing everywhere
LLMs consume repo-derived text.

Implementation notes:

- Reuse existing security sensor patterns for pre-runtime context scans.
- Add prompt framing to evidence synthesis prompts, not only builder/reviewer
  prompts.
- Add SAST-style artifact sensor support for common Python security tools.
- Preserve local-first state and runtime-auth behavior while disclosing what
  secrets are intentionally passed to the runtime.

TODO:

- [x] Add pre-runtime secret scan for files likely to enter context.
- [x] Apply untrusted-content framing to evidence synthesis prompts.
- [x] Add Python SAST artifact sensor.
- [x] Add runtime auth-key exposure disclosure to evidence.
- [x] Add tests for prompt-injection framing on all LLM prompt builders.

## Milestone 7: Ownership, Docs, Observability, And Review Burden

CES should reduce reviewer work by surfacing a compact evidence quality state and
by making ownership/docs/observability gaps explicit.

Implementation notes:

- Add evidence quality states: `complete`, `missing_artifacts`, `manual_only`,
  `waived`, and `failed`.
- Put missing evidence and skipped checks first in decisioning output and builder
  reports.
- Add path/owner policy support for sensitive files.
- Detect public behavior/docs impact and require documentation evidence.
- Add observability checklist guidance for API/service changes.

TODO:

- [x] Add evidence quality state computation.
- [x] Add missing-evidence summary to `ces explain --view decisioning`.
- [x] Add missing-evidence summary to `ces report builder`.
- [x] Add path/owner approval policy model.
- [x] Add docs-impact detector.
- [x] Add docs evidence requirement for public behavior changes.
- [x] Add API/service observability acceptance template.
- [x] Add CLI/report snapshot tests for stable output style.

## Recommended Implementation Order

1. Complete Milestones 1 through 4 in one PR-sized slice because they share the
   completion, builder, and approval path.
2. Run focused unit tests for completion models, verifier behavior, sensors,
   runtime safety, and builder flow.
3. Update docs and operator guidance for new evidence requirements.
4. Implement Milestones 5 through 7 as separate slices to keep security,
   dependency, and reporting changes reviewable.

## Verification Plan

- Focused tests:
  - `uv run pytest tests/unit/test_harness/test_completion_evidence_policy.py -q`
  - `uv run pytest tests/unit/test_harness/test_sensor_artifact_policy.py -q`
  - `uv run pytest tests/unit/test_execution/test_runtime_side_effect_policy.py -q`
  - `uv run pytest tests/unit/test_cli/test_run_cmd.py -q`
- Broader gates:
  - `uv run ruff check src/ tests/`
  - `uv run ruff format --check src/ tests/`
  - `uv run mypy src/ces/ --ignore-missing-imports`
  - `uv run pytest tests/ -m "not integration" --cov=ces --cov-fail-under=90 --cov-report=term-missing -q -W error`
  - `uv build`
  - `uvx twine check dist/*`

## Residual Risks

- Deterministic sensors still cannot prove semantic correctness.
- Runtime adapters depend on the capabilities of external local CLIs.
- Codex workspace-write mode is disclosed and approval-gated, but CES still
  cannot enforce a per-tool allowlist through that adapter today.
- Expert users can intentionally opt out of verification sensors; CES must make
  that visible and auditable rather than impossible.
