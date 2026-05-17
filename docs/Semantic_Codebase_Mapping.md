# CES Semantic Codebase Mapping

CES includes a read-only semantic codebase mapping layer for brownfield planning and execution prompts. The layer gives the runtime a compact repo-specific map before it acts, without replacing CES governance, approval, review, or completion evidence.

## What it does

The layer builds three artifacts:

1. **Codebase map**: a concise map of important files, modules, packages, entrypoints, configs, tests, scripts, docs, and semantic relationships.
2. **Relevant-area selection**: an objective-specific shortlist of repo areas that matter for the current request, split into high-confidence and possible secondary areas.
3. **Persisted invariants**: short factual repo facts CES can reuse later in the run, such as CLI entrypoints, source packages, config surfaces, and test surfaces.

The mapper is deterministic and local. It does not call an LLM and does not modify files during scanning. Persistence is explicit and limited to `.ces/codebase/` artifacts created during the CES build context-preparation stage. CES refuses to write these artifacts through symlinked `.ces`, `.ces/codebase`, or artifact files so repository-controlled links cannot redirect writes outside the project.

## When it runs

During `ces build`, after CES has captured and validated the builder brief but before the runtime prompt is sent to the local agent, CES prepares codebase context for existing repositories.

The context is injected into the same prompt pack that already carries the builder request, constraints, acceptance criteria, governance reminders, promoted legacy requirements, and completion contract instructions.

Greenfield projects without repo/config signals skip the layer.

## Artifacts

When persistence is enabled, CES writes:

- `.ces/codebase/map.json`: read-only scan output with areas, entrypoints, configs, tests, docs, scripts, and relationships.
- `.ces/codebase/selection.json`: relevant-area selection for the current objective.
- `.ces/codebase/invariants.json`: stable factual invariants freshly derived from the current scan so later CES steps can reuse updated facts without preserving stale or repo-seeded guesses.

These files are operator-readable and agent-usable. They are intentionally compact and factual. Guesses should not be persisted as invariants. Existing invariant artifacts are replaced with currently derived CES-managed keys before prompt rendering, which prevents stale or malicious persisted facts from becoming prompt instructions.

## Prompt injection

`ces.cli._run_prompting.build_prompt_pack()` accepts `codebase_context` and renders a `Codebase Context` section with:

- artifact paths
- high-confidence relevant areas with reasons
- possible secondary areas
- persisted invariants with sources

This keeps runtime context focused on the objective rather than stuffing the whole repository into the prompt. Rendered values are normalized and framed as untrusted repository metadata, not instructions.

## Realistic examples

### Example 1: CLI behavior change

Objective:

```text
Change the CLI command behavior and prompt output.
```

Typical high-confidence areas:

- `src/ces/cli/run_cmd.py`: command/runtime path for `ces build` and `ces run` behavior.
- `src/ces/cli/_run_prompting.py`: prompt-pack construction for runtime execution context.

Typical secondary areas:

- `tests/unit/test_cli/test_run_cmd.py`: validation around command behavior.
- `tests/unit/test_codebase_mapping.py`: validation for mapping/context injection when the change touches codebase context.

Injected invariants may include that `pyproject.toml` exposes the `ces` CLI script and tests live under `tests/`.

### Example 2: Verification or test-command change

Objective:

```text
Update verification command inference for Python projects.
```

Typical high-confidence areas:

- `src/ces/verification/`: verification contracts, project detection, and command execution.
- `src/ces/cli/verify_cmd.py`: user-facing verification command boundary.
- `pyproject.toml`: CI/dev dependency and test command contract surface.

Typical secondary areas:

- `tests/unit/test_cli/test_verify_cmd.py`
- `tests/unit/test_verification/` or nearby verification contract tests when present
- documentation that states operator verification workflows

The runtime prompt receives only these focused areas and invariants instead of the full repo tree.

## Testing and debugging

Focused unit tests:

```bash
uv run pytest tests/unit/test_codebase_mapping.py -q
```

Prompt integration can be checked by asserting the rendered prompt includes `Codebase Context`, high-confidence areas, secondary areas, and persisted invariants.

Full local CI parity remains the normal CES quality gate:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/ces/ --ignore-missing-imports
uv run pytest tests/ -m "not integration" -q
```

If the map seems too broad, inspect `.ces/codebase/selection.json` first. The selector should prefer exact objective terms and entrypoint/config/test boundaries over broad context stuffing.
