# Controlled Execution System repository audit

Audit date: 2026-05-20  
Repository audited: `chrisduvillard/controlled-execution-system`  
Default branch inspected: `master`  
Package version observed: `0.1.30`

## Audit scope and method

This audit reviewed the public repository through the connected GitHub repository interface. I inspected the repository metadata, README, Quickstart, Troubleshooting, Security Policy, Contributing guide, packaging configuration, GitHub workflows, Dependabot, pre-commit config, `.gitignore`, `.env.example`, gitleaks config, selected source modules, selected test modules, runtime adapter code, local state handling, workspace-delta handling, security sensors, and local SQLite persistence.

I was not able to perform a local clone or run the full test suite in this environment because network cloning was unavailable. I also could not verify branch protection, repository secret-scanning settings, historical git contents, GitHub environment approval rules, or PyPI project settings from the source tree alone. Findings below distinguish observed evidence from items that need follow-up verification.

The repository appears to be a public Python CLI package that provides a local-first governance workflow for AI coding agents, with Codex CLI and Claude Code as local runtimes.

---

## Executive summary

The repository is much more mature than a typical alpha CLI project. It has strong public-readiness foundations: clear README and Quickstart docs, a Security Policy, a Code of Conduct, Contributing instructions, `.env.example`, CodeQL, Dependabot, pip-audit, a 90 percent coverage gate, release smoke tests, PyPI trusted publishing, explicit runtime-boundary disclosures, local state permission tightening, symlink checks for `.ces`, subprocess environment allowlisting, and secret redaction before persisted evidence.

I did not find obvious real secrets, credentials, private URLs, or tokens in the files and targeted code searches I inspected. The repo also deliberately excludes sensitive local state from builds and ignores `.ces/` and `.env`.

The main readiness concerns are not basic hygiene. They are sharper product-safety and correctness issues in the runtime and approval flow:

1. **Runtime prompts are passed as process arguments.** Both Codex and Claude adapter commands include the full prompt pack or manifest description in `argv`. This can expose sensitive task context through local process listings and can hit OS command-line length limits.
2. **The interactive wizard appears to conflate pre-run execution consent with post-run approval.** `_wizard_flow` asks whether to proceed with execution, then calls `_run_brief_flow(..., yes=True)`. `_run_brief_flow` later treats `yes=True` as auto-approval when there are no blockers. That weakens the product promise that approval is explicit and evidence-backed.
3. **Completion-gate failures can be masked by passing independent verification.** `_completion_verification_blockers` returns no blockers when independent verification passes, even if the runtime did not emit a valid `ces:completion` claim or the claim failed.
4. **Runtime transcript handling truncates and rewrites transcript files.** The Codex adapter reads a capped amount from runtime output and writes the scrubbed, capped text back to the transcript path. This can destroy the tail of a transcript that should be part of the audit trail.
5. **Secret scanning is configured but not enforced in CI.** `.gitleaks.toml` exists, but the CI and pre-commit configs I inspected do not run gitleaks. The in-code secret scrubber is useful but narrower than full repository secret scanning.
6. **The audit ledger has cryptographic integrity code, but no public verify command.** The Security Policy explicitly says there is not yet a public `ces audit verify` command. That limits operator confidence in the HMAC chain.

These issues are fixable and should be prioritized before positioning the repo as ready for broad public adoption.

---

## Critical issues

### P0-1: Runtime prompt packs are exposed in subprocess command arguments

**Where observed**

- `src/ces/execution/runtimes/adapters.py`
- `CodexRuntimeAdapter.run_task`
- `ClaudeRuntimeAdapter.run_task`

**What I saw**

The Codex adapter builds a command that includes `prompt_pack or manifest_description` as a direct command argument to `codex exec`. The Claude adapter does the same through the `-p` argument.

**Why this matters**

Process arguments are commonly visible to other same-host users or diagnostics tools through process listing utilities. They may also appear in crash diagnostics, monitoring, telemetry, shell wrappers, debug output, or runtime process-tree snapshots. CES prompts can contain repo context, file paths, acceptance criteria, business intent, policy text, snippets, and possibly secrets if an upstream scanner misses something.

There is also a correctness risk: large prompt packs can exceed platform-specific command-line length limits.

**Recommended fix**

Feed prompt content through a safer channel:

- Prefer stdin when the runtime supports it.
- Otherwise write the prompt to a project-local 0600 temp file under `.ces/runtime-prompts/`, pass only the file path if the runtime supports a prompt-file mode, then scrub and delete it or retain a redacted hash-only record.
- Ensure timeout diagnostics and process-tree snapshots never include prompt body text.
- Add a regression test that asserts no operator prompt content appears in `subprocess.Popen` command arguments.

**Suggested owner**

Execution/runtime adapter owner.

---

### P0-2: Interactive wizard appears to auto-approve after pre-run confirmation

**Where observed**

- `src/ces/cli/run_cmd.py`
- `_wizard_flow`
- `_run_brief_flow`

**What I saw**

The wizard asks:

```text
Proceed with execution?
```

Then it calls `_run_brief_flow(..., yes=True)` to avoid double prompting. Later `_run_brief_flow` sets:

```python
approved = yes and not auto_blockers
```

For interactive usage, this looks like a pre-runtime confirmation is reused as post-evidence approval.

**Why this matters**

The product repeatedly promises explicit approval based on evidence, not on runtime confidence. A user can reasonably interpret “Proceed with execution?” as permission to run the agent, not permission to approve the resulting change after evidence is generated. If a runtime exits successfully and no automatic blocker fires, the wizard may record approval without a second user decision.

**Recommended fix**

Separate execution consent from approval consent:

- Add an internal flag such as `execution_confirmed=True` or `skip_execution_prompt=True`.
- Keep `yes=False` for approval unless the user explicitly passed `--yes`.
- After evidence is generated, prompt with a distinct approval question such as:
  - `Approve this evidence packet?`
  - `Record approval for this manifest?`
- Add a test proving the default wizard path prompts after evidence and does not auto-approve.
- Keep non-interactive `--yes` strict and evidence-gated.

**Suggested owner**

Builder flow and CLI UX owner.

---

### P0-3: Completion-gate failure can be overridden by independent verification success

**Where observed**

- `src/ces/cli/run_cmd.py`
- `_completion_verification_blockers`

**What I saw**

The blocker function returns an empty blocker list whenever `independent_verification.passed` is true, before considering whether the completion claim was missing, malformed, or failed verification.

**Why this matters**

The docs and prompt contract say a governed run must emit a valid `ces:completion` block. That claim is important because it binds the runtime’s assertion to acceptance criteria, changed files, verification commands, dependency changes, complexity notes, open questions, and scope deviations.

Independent commands passing is good evidence, but it is not a substitute for the runtime’s structured completion claim. A test suite can pass while the runtime omits changed files, hides uncertainty, misses acceptance criteria, or fails to disclose scope deviation.

**Recommended fix**

Treat completion-claim validity and independent verification as separate gates:

- Missing or malformed completion claim should block when completion gate sensors are enabled.
- A failed completion verification should block even if independent commands pass.
- Independent verification can improve confidence and remove command-related blockers, but it should not erase structured completion-contract blockers.
- Add regression tests for:
  - missing completion claim plus passing independent verification
  - malformed claim plus passing independent verification
  - valid claim plus failing independent verification
  - both valid and passing

**Suggested owner**

Verification and builder evidence owner.

---

### P0-4: Runtime transcript files are truncated and rewritten

**Where observed**

- `src/ces/execution/runtimes/adapters.py`
- `_read_scrubbed_limited_path`
- `CodexRuntimeAdapter.run_task`

**What I saw**

The adapter reads at most `_MAX_RUNTIME_OUTPUT_BYTES + 1`, scrubs that limited text, and writes it back to the transcript path. With the default 1 MiB cap, this can replace a longer transcript with only the first 1 MiB plus a truncation marker.

**Why this matters**

CES’s core value is evidence and auditability. Destroying the tail of a runtime transcript weakens incident review, reproducibility, and user trust. It also creates a mismatch between “runtime transcript” and “UI excerpt.”

**Recommended fix**

Keep two separate artifacts:

- A full transcript artifact, scrubbed as it is written or scrubbed into a separate full redacted transcript.
- A capped excerpt for database storage and CLI display.

Add a test that writes output above the cap and verifies the full transcript artifact remains available, while persisted evidence uses a capped excerpt.

**Suggested owner**

Execution evidence owner.

---

## Security and public repo risks

### What looks good

#### No obvious committed real secrets in inspected files

I did not find obvious real API keys, tokens, private keys, credentials, or private URLs in the root docs/configs/source files I inspected or in targeted repository searches for common token strings. `.env.example` contains only safe placeholders and explicitly tells users not to commit `.env`.

This does not prove the entire repository history is clean. A full `gitleaks detect` scan across history should still be run locally or in CI.

#### `.env.example` is appropriate

`.env.example` explains that most users do not need environment configuration, that `ces init` generates project-local audit keys, and that `.env` must never be committed. It keeps `CES_AUDIT_HMAC_SECRET` commented and blank.

#### Runtime environment allowlisting is strong

`src/ces/execution/_subprocess_env.py` builds a restricted subprocess environment and preserves only base OS/runtime needs plus runtime-specific auth variables. It strips credentials embedded in proxy URLs. This is a good design choice for avoiding leakage of unrelated host secrets such as AWS credentials, database URLs, or GitHub tokens.

#### Local state path and symlink handling are strong

`src/ces/local_state_path.py` rejects symlinked `.ces` directories and CES state paths that escape the project root. The runtime transcript path code also rejects symlinked `.ces/runtime-transcripts`.

#### SQLite state permissions are tightened

`src/ces/local_store/store.py` creates the SQLite state DB under `.ces`, then attempts to set `.ces` to 0700 and `state.db` plus the lock file to 0600. That matches the security model documented in `SECURITY.md`.

#### GitHub workflows use least privilege in obvious places

The CI workflow sets `contents: read`. Publish workflows use `id-token: write` plus `contents: read`, which is appropriate for trusted publishing. CodeQL has `security-events: write`.

#### Supply-chain hygiene is better than average

The project has:

- Dependabot for GitHub Actions and uv dependencies
- `pip-audit --strict` in CI and release workflows
- CodeQL on push, PR, and weekly schedule
- frozen dependency installs in normal CI
- a separate latest-allowed-dependency job
- build metadata checks
- installed-wheel smoke tests
- release tag/version/changelog agreement checks

### Risks and gaps

#### Secret scanning is not enforced in CI or pre-commit

`.gitleaks.toml` exists, but I did not see gitleaks invoked in `.github/workflows/ci.yml` or `.pre-commit-config.yaml`.

**Risk**

A real secret could be committed even though the repo has a gitleaks config.

**Fix**

Add:

```yaml
- name: Scan repository for secrets
  run: |
    uv tool run gitleaks detect --source . --redact --no-git
```

For full-history scans, run gitleaks in a local clone or a CI job that has full history.

Also add a pre-commit hook for gitleaks or detect-secrets.

#### `.gitignore` should cover more public-repo local artifacts

The current `.gitignore` covers `.env`, `.ces/`, `.venv/`, Python caches, build outputs, several internal scratch dirs, and `*.private_key`.

Recommended additions:

```gitignore
# Environment variants
.env.*
!.env.example

# Logs and diagnostics
*.log
*.log.*
runtime-transcripts/
dogfood-output/

# Local caches and tool state
.uv-cache/
.mcp.json

# Databases and local state
*.db
*.sqlite
*.sqlite3
*.db-shm
*.db-wal

# Secrets and key material
*.pem
*.key
*.crt
*.cer
*.p12
*.pfx
id_rsa
id_dsa
id_ecdsa
id_ed25519
*.kubeconfig
credentials.json
secrets.json
.pypirc
.npmrc
.netrc
```

Be careful with broad `*.key` if the repo intentionally tracks non-secret public key fixtures. If so, use explicit exceptions.

#### The in-code secret scrubber is useful but narrow

`src/ces/shared/secrets.py` scrubs known prefixes such as `sk-`, `ghp_`, `ghs_`, `AKIA`, `xoxb-`, and `xoxp-`, plus key-value assignments. `src/ces/harness/sensors/security.py` catches AWS access keys, private key headers, GitHub `ghp_` or `ghs_` style tokens, generic API key assignments, password assignments, and high-entropy secret assignments.

Missing or weakly covered examples include:

- GitHub fine-grained personal access tokens, such as `github_pat_...`
- GitLab tokens, such as `glpat-...`
- Slack `xoxc-`, `xoxa-`, and related variants
- JWTs beginning with `eyJ...`
- DSNs and URLs containing credentials, such as `postgres://user:pass@host/db`
- multiline private key bodies
- Google service account JSON patterns
- Azure and cloud-specific secrets
- unquoted assignment values in the security sensor
- high-entropy values under less obvious names

**Fix**

Keep the lightweight in-code scrubber, but do not rely on it as the only defense. Add gitleaks in CI and broaden redaction patterns for persisted runtime output.

#### Runtime auth variables are intentionally passed to runtimes

Codex receives OpenAI-related environment variables and Claude receives Anthropic-related variables. This is expected, because those CLIs need auth. It should be documented in a short “data and credentials boundary” section:

- CES strips unrelated host secrets.
- Runtime-specific auth variables still go to the selected runtime.
- Prompt content and repository context may be sent to the runtime provider by the runtime CLI.
- Users should run with isolated credentials for sensitive work.

#### GitHub Actions are pinned by version tag, not commit SHA

The workflows use action references such as `actions/checkout@v6`, `astral-sh/setup-uv@v7`, `github/codeql-action/init@v4`, and `pypa/gh-action-pypi-publish@release/v1`.

This is normal, but for a security-focused public repo, pinning actions to full commit SHAs would reduce supply-chain risk.

#### Branch protection and environment approvals could not be verified

The workflow files are good, but source files cannot prove:

- branch protection is enabled
- required checks are enforced
- release tags are protected
- PyPI and TestPyPI environments require approval or trusted-publishing restrictions
- GitHub secret scanning and push protection are enabled

Add these to the maintainer checklist.

---

## Code quality issues

### 1. `src/ces/cli/run_cmd.py` is too large and mixes too many responsibilities

`run_cmd.py` is the biggest maintainability risk I inspected. It combines:

- Typer command definitions
- interactive wizard UX
- non-interactive validation
- intent gate handling
- manifest creation and signing
- runtime safety checks
- brownfield behavior handling
- workspace snapshots
- runtime execution
- completion claim parsing
- independent verification
- sensor orchestration
- evidence persistence
- approval and merge workflow transitions
- session recovery updates
- user-facing Rich output

This makes it harder to reason about failure modes and increases the risk that a future fix in one area changes approval or evidence behavior elsewhere.

**Recommended refactor**

Split into services with explicit boundaries:

- `BuilderInputValidator`
- `BuilderSessionService`
- `RuntimeExecutionService`
- `EvidenceAssemblyService`
- `CompletionGateService`
- `ApprovalDecisionService`
- `BuilderCliRenderer`

Keep Typer functions thin.

### 2. Runtime execution normalization is duplicated

`src/ces/execution/pipeline.py` defines `normalize_runtime_execution`, while `src/ces/cli/run_cmd.py` defines `_normalize_runtime_execution`. The CLI version scrubs stdout/stderr, while the shared pipeline version does not.

**Risk**

A future caller could use the shared normalization path and persist or display unsanitized runtime output.

**Fix**

Create one public normalization function that always scrubs stdout/stderr. Use it everywhere. Add tests that both dict and object runtime results are scrubbed.

### 3. The project advertises strict mypy but disables many strict checks

`pyproject.toml` has `strict = true`, but then disables or relaxes many checks, including untyped calls, untyped defs, incomplete defs, subclassing Any, Any generics, return Any warnings, unused ignores, and many error codes.

This is not dishonest if intentional, but it can mislead contributors. It also reduces the confidence normally associated with “strict mypy.”

**Fix**

Either:

- rename the docs to “mypy with current compatibility relaxations,” or
- gradually restore strictness by module, starting with security-critical and runtime-boundary code.

### 4. Coverage gate excludes legacy CLI command modules

Coverage omits several CLI command modules: `audit_cmd.py`, `classify_cmd.py`, `gate_cmd.py`, `intake_cmd.py`, `report_cmd.py`, and `triage_cmd.py`.

The comment explains why, but these are still public commands. For a public CLI, command entry points should have at least smoke and error-path tests.

**Fix**

Add command-level tests before removing the omit list.

### 5. The CLI command registry is large and manually wired

`src/ces/cli/__init__.py` imports many command modules and registers them manually. This is acceptable today, but it will keep growing and increase import-time coupling.

**Fix**

Consider a declarative command registry list for simple commands, keeping custom Typer groups explicit.

### 6. Source-tree fallback version can drift

`src/ces/__init__.py` falls back to hardcoded version `0.1.30` when package metadata is unavailable. That can drift from `pyproject.toml`.

**Fix**

Read the source-tree version from `pyproject.toml` in the fallback path, or add a unit test that asserts fallback and project version match.

### 7. Docs and planning files may be overrepresented for a public repo

The repo has many docs, plans, scenario matrices, and dogfood artifacts. The packaging excludes `docs/plans`, but the public repository can still feel noisy to new users.

**Fix**

Keep historical and planning docs, but add a stronger docs index with “start here,” “maintainer-only,” “historical,” and “design archive” labels.

---

## Logic and implementation issues

### 1. Completion gate should remain mandatory when configured

As described in critical issue P0-3, passing independent verification should not clear missing or failed completion-claim evidence. The runtime’s structured claim is part of the governance contract.

### 2. Approval semantics need clearer separation

The code should keep these concepts separate:

- permission to create local `.ces` state
- permission to launch a runtime
- permission to accept runtime side effects
- permission to approve evidence
- permission to mark ready to ship or merge

Right now the wizard path appears to blur runtime execution confirmation and evidence approval.

### 3. Brownfield scope handling has a good principle, but needs more confidence tests

The code explicitly says observed brownfield runtime edits are evidence, not authorization. Tests confirm source-of-truth and critical-flow paths are used instead of laundering runtime-created files into scope. That is a strong design choice.

More tests should cover:

- existing manifest with partial scope
- deleted files
- generated files
- nested packages
- files renamed by runtime
- path extraction false positives from prose
- critical flow text containing non-path names
- source-of-truth directories, glob-like paths, and Windows paths

### 4. Workspace snapshots skip some state but still need policy clarity

`WorkspaceSnapshot.capture` excludes `.git`, caches, build/dist, virtualenvs, and `.ces/runtime-transcripts/`, plus `.ces/state.db-shm`. It does not exclude all `.ces` state. That can be useful for catching local governance writes, but it can also mix product changes with CES internal changes.

The code later filters `.ces` out for greenfield inferred product scope. This needs clear policy:

- Which `.ces` files are expected to change during a build?
- Which `.ces` files should never be product-scope evidence?
- Which `.ces` files are allowed to be tracked intentionally, such as shared verification profiles?

### 5. Runtime timeout handling is strong, but prompt-in-argv undermines diagnostics

Timeout diagnostics include process-tree snapshots and command labels. The code scrubs process labels, but if the full prompt is in argv, diagnostics must rely on scrubber coverage to avoid exposing context. Removing prompt body from argv fixes this more robustly.

### 6. Security sensor reads only files up to 1 MiB

`read_file_safe` skips files above 1 MiB. That is sensible for performance, but large files can contain secrets, especially logs, generated configs, or lockfiles.

**Fix**

For security scanning, either scan large files in chunks or record a warning finding that a large file was skipped.

### 7. Gitleaks allowlist should be reviewed after enabling CI

`.gitleaks.toml` allowlists a few fake values. Once gitleaks is wired into CI, validate that the allowlist is not too broad. The `***` allowlist is probably harmless but should be justified because it can mask some synthetic patterns.

---

## Tests and validation

### Existing test and validation strengths

The repo has a strong validation story:

- Ruff linting and format checks
- mypy checks
- pytest with coverage fail-under 90
- pip-audit in CI and release workflows
- vulture high-confidence dead-code ratchet
- CodeQL
- release tag/version/changelog validation
- wheel and sdist metadata checks
- installed CLI smoke tests
- runtime adapter tests
- secret stripping tests
- brownfield scope tests
- non-interactive `--yes` guard tests
- Codex side-effect boundary smoke tests
- TestPyPI and PyPI workflows

This is a very good foundation.

### Missing tests to add

#### Security and public repo safety

1. **CI secret scan test**
   - Add gitleaks to CI and pre-commit.
   - Add a test or script that fails if `.gitleaks.toml` exists but no CI job references gitleaks.

2. **`.gitignore` contract tests**
   - Assert `.env`, `.env.local`, `.env.production`, `.ces/keys/`, `.mcp.json`, local DBs, logs, and common key files are ignored.
   - Assert `.env.example` is not ignored.

3. **Secret scrubber expansion tests**
   - `github_pat_`
   - `glpat-`
   - JWTs
   - DSNs with passwords
   - private key blocks
   - Google service account JSON
   - multiline secrets
   - proxy URLs with embedded credentials

4. **Large file security-scan test**
   - Verify that large skipped files produce a warning or are scanned in chunks.

#### Runtime and evidence

5. **Prompt not passed in argv**
   - Test that runtime `Popen` commands do not include prompt body text.

6. **Transcript preservation test**
   - Verify full redacted transcript remains available after output exceeds the display cap.

7. **Completion-gate independence tests**
   - Missing completion claim plus passing independent verification must block.
   - Failed completion claim plus passing independent verification must block.
   - Valid completion claim plus failed independent verification must block.
   - Both valid and passing should allow progress.

8. **Runtime timeout artifact tests**
   - Confirm timeout diagnostics do not include unsanitized prompt content.
   - Confirm process-tree labels are redacted.

#### Approval flow

9. **Wizard post-evidence approval test**
   - Default interactive wizard should ask a post-evidence approval question.
   - Pre-runtime “Proceed with execution?” should not record approval.

10. **`--yes` approval boundary tests**
   - Ensure `--yes` auto-approval still blocks on missing completion claim, scope violation, failed independent verification, failed sensor policy, and unaccepted runtime side-effect risk.

#### Public CLI command coverage

11. **Smoke tests for omitted CLI modules**
   - `audit`, `classify`, `gate`, `intake`, `report`, `triage`
   - Include help, invalid input, JSON output, and minimal happy path.

12. **Audit ledger verify command tests**
   - Once added, test valid chain, tampered entry, wrong previous hash, wrong HMAC secret, and missing key.

#### Documentation

13. **Docs link checker**
   - Ensure README and docs links resolve within repo.
   - Ensure command examples are still valid Typer commands.

14. **Quickstart golden-output tests**
   - Snapshot key output from `ces create`, `ces start`, `ces doctor --runtime-safety`, `ces cleanup`, and `ces proof`.

---

## Documentation and onboarding gaps

### What is strong

The documentation is extensive and unusually careful about boundaries. It explains:

- CES is not a sandbox.
- CES is not a hosted control plane.
- Runtime credentials stay with Codex or Claude.
- `.ces/` stores local state.
- `ces create`, `ces start`, and `ces ship` are read-only.
- Codex requires explicit side-effect consent.
- `--yes` is stricter for brownfield automation.
- Approval should follow `ces verify` and `ces proof`.
- Cleanup and uninstall steps exist.
- Troubleshooting covers missing runtime, Python version issues, demo mode, Codex runtime safety notices, and wrong-directory mistakes.

### Main friction for vibe coders

The README is comprehensive but dense. A new user building from scratch may struggle to answer:

- Which command do I run first?
- Which commands are read-only?
- Which command actually launches the agent?
- Why did Codex stop and ask for side-effect acceptance?
- What does a good proof result look like?
- What should I paste into my coding agent versus what does CES run itself?
- What do I do when proof is partially proven?

**Recommendation**

Add a short “First 15 minutes” guide with only one path:

```bash
uv tool install --python 3.13 controlled-execution-system
ces doctor
ces create "Create a small task tracker with tests and a README" --name task-tracker
mkdir task-tracker && cd task-tracker
ces build --from-scratch "Create a small task tracker with tests and a README"
ces verify
ces proof
```

Then show expected outputs and one common failure.

### Main friction for experienced developers

Experienced developers will want stronger contracts:

- JSON schemas for `.ces/completion-contract.json`, `.ces/verification-profile.json`, evidence packets, proof cards, and builder sessions
- exact exit-code semantics
- CI integration examples
- policy-as-code examples
- recommended branch protection settings
- how to run CES in a monorepo
- how to configure runtimes without leaking unrelated environment variables
- how to verify audit integrity
- how to export evidence for PR review

### Documentation gaps to fill

1. **Data boundary and privacy page**
   - What data CES stores locally
   - What data goes to Codex or Claude
   - Which environment variables are passed through
   - What is scrubbed before persistence
   - What is not guaranteed to be scrubbed

2. **Audit integrity page**
   - How Ed25519 signing works
   - How HMAC chain works
   - How to rotate keys
   - How to verify the ledger once `ces audit verify` exists

3. **Runtime adapter matrix**
   - Claude vs Codex
   - tool allowlist
   - workspace scoping
   - network behavior
   - side-effect consent
   - MCP support
   - expected auth variables

4. **Brownfield playbook**
   - examples for small feature, refactor, dependency upgrade, database migration, and security patch
   - how to pick source-of-truth files
   - how to write `--must-not-break`
   - how to interpret unknown behavior deltas

5. **Failure-mode guide**
   - runtime missing
   - runtime timeout
   - missing completion claim
   - failed verification
   - scope violation
   - sensor policy blocker
   - proof partially proven
   - cleanup and retry

6. **Maintainer public-release checklist**
   - gitleaks full-history scan
   - branch protection
   - required checks
   - protected tags
   - GitHub secret scanning and push protection
   - PyPI trusted publisher status
   - TestPyPI validation
   - action SHA pinning review

---

## Product usefulness

### For greenfield projects

CES can be very useful for greenfield projects because it forces:

- acceptance criteria
- small scope
- proof-backed completion
- tests and run instructions
- README handoff
- anti-slop simplicity constraints

To make it more valuable without adding complexity:

1. **Offer starter templates only as prompt contracts, not generated frameworks**
   - Python CLI
   - FastAPI service
   - Next.js app
   - simple static site
   - package/library
   - data script
   - test-only spike

2. **Add “boring defaults”**
   - minimal test command
   - minimal README checklist
   - minimal lint command if detected
   - dependency budget
   - “no new framework unless requested”

3. **Generate acceptance criteria suggestions**
   - Ask user to accept/edit three concise criteria before build.
   - For `--yes`, require explicit user-provided criteria as the code already does.

4. **Show a beginner proof card**
   - What changed
   - How to run
   - How to test
   - What remains unproven
   - Whether it is safe to review

5. **Add examples of bad prompts and improved CES prompts**
   - “Build me a SaaS app”
   - “Create a task tracker with add/list/complete, CLI tests, README, no external services”

### For brownfield projects

CES’s biggest opportunity is brownfield risk reduction. The current architecture already leans that way with MRI, next-prompt, must-not-break rules, source-of-truth files, workspace delta checks, behavior deltas, and proof cards.

To improve usefulness:

1. **Make source-of-truth selection easier**
   - `ces next-prompt` could suggest likely test/docs/source files from repo mapping.
   - Let users accept or edit suggestions.

2. **Add change-type playbooks**
   - dependency upgrade
   - API change
   - database migration
   - security patch
   - UI change
   - test stabilization
   - refactor

3. **Improve test selection**
   - Map changed files to likely tests.
   - Show “required,” “recommended,” and “missing” checks.

4. **Add monorepo support docs**
   - package root detection
   - multiple verification profiles
   - subproject `.ces` state
   - workspace-level proof cards

5. **Integrate proof into PR workflows**
   - `ces review github-comment --dry-run` appears to exist.
   - Add a complete “CES in a pull request” guide.

### For public adoption

The product is promising, but public users need trust in the boundary claims. The biggest trust wins would be:

- no prompt body in process argv
- no transcript evidence loss
- no auto-approval ambiguity
- gitleaks in CI
- public audit verification command
- concise data-boundary docs

---

## Recommendations for vibe coders

A vibe coder wants the tool to keep them from getting lost, overbuilding, or shipping unverified work. Prioritize:

1. **Make the first path impossible to misunderstand**
   - one command sequence
   - clear read-only vs mutating labels
   - expected output screenshots or snippets

2. **Use stronger default prompts**
   - “smallest boring solution”
   - “no new services”
   - “tests and README required”
   - “list unproven risks”

3. **Add beginner examples**
   - task tracker
   - notes app
   - landing page
   - API endpoint
   - bug fix in existing app

4. **Turn proof into a simple checklist**
   - can I run it?
   - can I test it?
   - what changed?
   - what did not get proven?
   - should I review or retry?

5. **Make cleanup obvious**
   - `ces cleanup --project-root .`
   - `ces cleanup --project-root . --yes`
   - `uv tool uninstall controlled-execution-system`

6. **Provide “safe copy-paste” snippets**
   - avoid long tables for the first path
   - provide one exact command at a time

---

## Recommendations for experienced developers

Experienced developers will care less about the wizard and more about correctness, automation, and boundaries.

Prioritize:

1. **Machine-readable contracts**
   - publish JSON schemas
   - stable exit codes
   - stable evidence packet shape
   - stable proof card shape

2. **Policy-as-code**
   - configurable approval gates
   - verification profile examples
   - forbidden path patterns
   - dependency-change rules
   - runtime policy rules

3. **CI and PR integration**
   - GitHub Actions template
   - GitLab template
   - PR comment proof card
   - artifact upload examples
   - fail-on-unproven example

4. **Audit verification**
   - `ces audit verify`
   - tamper report
   - key rotation guidance
   - exportable signed proof bundle

5. **Runtime boundary hardening**
   - no prompt in argv
   - file or stdin based prompts
   - explicit data boundary docs
   - isolated runtime environment docs

6. **Monorepo and brownfield workflows**
   - subproject root selection
   - verification profiles per package
   - source-of-truth discovery
   - behavior-preservation examples

---

## Suggested improvements ranked by priority

### P0: Fix before broad public adoption

| Priority | Improvement | Why it matters | Suggested validation |
|---|---|---|---|
| P0 | Stop passing prompt packs in subprocess argv | Prevents local process-list exposure and command length failures | Test that prompt text is absent from `Popen` command args |
| P0 | Separate execution consent from approval consent | Preserves explicit evidence-backed approval promise | Wizard test requiring post-evidence approval prompt |
| P0 | Make completion-gate failures independent blockers | Prevents passing tests from masking missing structured completion evidence | Regression tests for missing or failed completion claim |
| P0 | Preserve full runtime transcripts separately from capped excerpts | Protects auditability | Oversized-output transcript preservation test |

### P1: High priority public safety and trust

| Priority | Improvement | Why it matters | Suggested validation |
|---|---|---|---|
| P1 | Add gitleaks to CI and pre-commit | Prevents accidental public secret publication | CI fails on synthetic secret fixture |
| P1 | Strengthen `.gitignore` | Prevents local logs, DBs, keys, and env variants from being committed | `.gitignore` contract test |
| P1 | Expand secret redaction and security sensor patterns | Reduces leakage in evidence and runtime output | Token-format test matrix |
| P1 | Add `ces audit verify` | Lets users verify HMAC audit-chain claims | Tamper tests |
| P1 | Add data-boundary docs | Builds user trust and avoids overclaiming | Docs link and content check |

### P2: Maintainability and polish

| Priority | Improvement | Why it matters | Suggested validation |
|---|---|---|---|
| P2 | Split `run_cmd.py` into services | Reduces coupling and hidden approval/evidence interactions | Unit tests by service |
| P2 | Centralize runtime normalization and scrubbing | Avoids future unsanitized persistence | Shared normalization tests |
| P2 | Reconcile mypy “strict” messaging with relaxed config | Avoids contributor confusion | Type coverage ratchet |
| P2 | Bring omitted CLI modules under coverage | Public commands deserve tests | Remove coverage omit list gradually |
| P2 | Pin GitHub Actions to SHAs | Improves supply-chain posture | Release checklist item |
| P2 | Add docs index by audience | Reduces onboarding friction | README link check |

### P3: Product expansion without unnecessary complexity

| Priority | Improvement | Why it matters | Suggested validation |
|---|---|---|---|
| P3 | Add greenfield prompt-contract templates | Helps beginners without adding runtime complexity | Golden prompt tests |
| P3 | Add brownfield change-type playbooks | Makes experienced workflows faster | Example repo tests |
| P3 | Add monorepo guide | Useful for real teams | Docs examples |
| P3 | Add proof-card PR examples | Helps adoption in team workflows | GitHub comment snapshot tests |

---

## Concrete next steps

### Week 1: safety fixes

1. Change runtime adapters so prompt text is not placed in command arguments.
2. Add regression tests proving prompt text is not in `Popen` argv.
3. Fix wizard approval semantics so interactive users explicitly approve after evidence.
4. Fix `_completion_verification_blockers` so completion claim failures remain blockers.
5. Preserve full redacted runtime transcripts and store only capped excerpts in SQLite/UI.
6. Add gitleaks to CI and pre-commit.
7. Strengthen `.gitignore`.

### Week 2: trust and verification

1. Add `ces audit verify`.
2. Expand secret redaction and security sensor token coverage.
3. Add large-file skipped-warning behavior to the security sensor.
4. Add a data-boundary document.
5. Add a runtime adapter matrix document.
6. Add public release checklist items for branch protection, tag protection, GitHub secret scanning, push protection, and PyPI trusted publishing.

### Week 3: maintainability

1. Extract builder-flow services from `run_cmd.py`.
2. Centralize runtime execution normalization and scrubbing.
3. Add tests for omitted CLI command modules.
4. Start restoring mypy strictness by module, beginning with runtime, crypto, local state, and verification.
5. Add docs link checking.

### Week 4: onboarding and product usefulness

1. Add a “First 15 minutes” guide.
2. Add a “First brownfield change” guide.
3. Add beginner proof-card examples.
4. Add experienced developer CI/PR integration examples.
5. Add greenfield and brownfield prompt-contract examples.

---

## Overall readiness assessment

### Safe for public viewing

Mostly yes. I did not find obvious secrets in inspected files, the repo has a Security Policy, `.env.example` is safe, `.ces/` and `.env` are ignored, package exclusions are thoughtful, and CI/release hygiene is strong.

### Safe for broad public use

Not yet. The tool is promising and already has unusually strong controls, but the subprocess prompt exposure, approval-flow ambiguity, completion-gate masking, transcript truncation, and missing enforced secret scanning should be fixed before encouraging many users to rely on it.

### Clean and maintainable

Partly. The architecture has clear planes and many good abstractions, but `run_cmd.py` is too large and centralizes too much critical behavior. Some quality gates are softened by mypy relaxations and coverage omissions.

### Useful

Yes. The product concept is useful for both greenfield and brownfield AI-assisted software delivery. Its strongest differentiator is the proof/evidence loop. The highest-leverage product improvements are not flashy new features. They are stronger trust boundaries, simpler onboarding, and clearer machine-readable contracts.

---

## Final recommendation

Treat the repository as a strong alpha that is close to public-ready, not as a finished public safety tool. Prioritize boundary correctness and trust first:

1. no prompt body in argv
2. explicit post-evidence approval
3. completion claims cannot be bypassed by passing tests
4. full transcript preservation
5. gitleaks enforced in CI
6. public audit verification

After those are fixed, the repo would be in a much better position to invite broader usage.
