## Summary

<!-- What does this PR do? -->

## Test Plan

- [ ] New tests added
- [ ] All quality gates pass (`uv run ruff check . && uv run pyright && uv run tach check && uv run pytest -q`)

## Checklist

- [ ] No subprocess or real filesystem calls in production code
- [ ] Type annotations on all new functions
- [ ] `tach.toml` updated if new inter-module imports were added
