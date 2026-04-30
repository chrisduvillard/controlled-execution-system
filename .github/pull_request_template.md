## Summary

Describe the user-facing or operational change in 2-4 sentences.

## Verification

- [ ] `uv run ruff check src/ tests/`
- [ ] `uv run ruff format --check src/ tests/`
- [ ] `uv run mypy src/ces/ --ignore-missing-imports`
- [ ] `uv run pytest tests/unit/ -q -W error`

## Deployment Notes

- [ ] No special deployment changes
- [ ] Docs updated if the public contract changed
- [ ] Follow-up work tracked if anything was intentionally deferred
