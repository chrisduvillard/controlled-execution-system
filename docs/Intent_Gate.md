# Intent Gate

Intent Gate is the pre-manifest safety check in the CES builder flow. It classifies the operator's plain-language request before manifest creation so CES can preserve momentum for clear work while stopping or clarifying risky ambiguity.

The gate creates a specification ledger from the request, constraints, acceptance criteria, and project mode. The ledger is context for the builder and operator; it is not a permission source and does not override manifest policy.

## Decisions

Intent Gate returns one of four decisions:

- `proceed`: the request has enough acceptance criteria or boundaries for CES to move directly toward manifest creation.
- `assume_and_proceed`: the request is low risk or narrow enough for CES to record a conservative assumption and continue. Operators should inspect the assumption and keep the change minimal.
- `ask`: the request is ambiguous in a way that matters for safety or correctness, so an interactive run should ask the operator for clarification before building the manifest.
- `blocked`: the request cannot safely continue in the current mode. This is most common when a high-risk request lacks acceptance criteria during a non-interactive run.

## Non-interactive safety

In interactive builder sessions, Intent Gate can ask for missing acceptance criteria, failure boundaries, or scope constraints. In non-interactive sessions, CES cannot rely on a human answer, so high-risk ambiguous requests become `blocked` instead of `ask`.

Use `--acceptance` to provide explicit success criteria up front when launching a request that touches risky areas such as authentication, authorization, data deletion, database changes, billing, production behavior, credentials, security-sensitive paths, releases, publishes, merges, deploys, or customer-facing messages.

## Modes

Intent Gate can be configured by mode:

- `off`: skip Intent Gate classification and continue with the existing builder behavior.
- `rules`: use deterministic local rules for risk and ambiguity classification.
- `strict`: apply conservative rules that favor clarification or blocking when important details are missing.
- `llm`: use the LLM-assisted classifier path when configured, with deterministic fallback behavior available for safety.

`--reverse-preflight` controls whether CES runs the preflight before manifest creation in flows that support the builder preflight path. Keep it enabled when you want Intent Gate to catch ambiguity before the manifest is drafted.

## Examples

### Fix login

```bash
ces build "Fix login"
```

Login and authentication work is high risk. Without acceptance criteria, an interactive run should return `ask` and request boundaries such as expected login behavior, failure modes, affected user types, and verification. A non-interactive run should not guess.

A safer launch includes explicit acceptance criteria:

```bash
ces build "Fix login token refresh" \
  --acceptance "Expired access tokens refresh once using a valid refresh token" \
  --acceptance "Invalid refresh tokens keep returning 401 without creating a session"
```

### README cleanup

```bash
ces build "Tighten the README wording in the installation section"
```

README wording is low risk. If no acceptance criteria are provided, Intent Gate may return `assume_and_proceed` and record an assumption such as making only a conservative wording change after inspecting the file.

### Database deletion

```bash
ces build "Delete stale rows from the production database" --yes
```

Database deletion is high risk. In non-interactive mode, missing acceptance criteria or failure boundaries should return `blocked`. Provide explicit acceptance criteria, constraints, and verification before attempting this kind of work.

### External release or messaging action

```bash
ces build "Push the release tag and publish to PyPI" --yes
```

Release, merge, publish, deploy, and customer-message requests cross an external side-effect boundary. In non-interactive mode, missing acceptance criteria should return `blocked`; interactive mode should ask for explicit scope, rollback, and verification boundaries first.

## Safety model

Intent Gate narrows intent before manifest creation; it does not grant runtime authority. The specification ledger is context for the builder, reviewers, and downstream evidence. Manifest policy remains the authority for allowed paths, commands, approval gates, and execution boundaries.
