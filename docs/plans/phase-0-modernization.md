# Phase 0: Repo modernization

Small cleanup, no new features. Already on `uv` (uv.lock, hatchling backend).

## Scope

1. pyproject cleanup:
   - Delete the dead `[tool.setuptools.packages.find]` section (backend is
     hatchling).
   - Collapse the duplicated dev deps: Keep `[dependency-groups]`, drop
     `[project.optional-dependencies]`.
2. Add `ruff` (lint + format) with basic config, fix any findings.
3. Commit the pending research doc and .gitignore changes.

## Non-goals

- Keep `selenium` and `download/`: The scrapers are dead but may inform the
  Phase 4 rebuild. Delete after rebuild, not before.
- No dependency additions beyond ruff. `beancount` lands in Phase 1.

## Acceptance

- `uv sync` clean, `ruff check` and `ruff format --check` pass, tests pass.
