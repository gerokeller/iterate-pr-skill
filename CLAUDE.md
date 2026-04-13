# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A [Claude Code skill](https://docs.claude.com/en/docs/claude-code/capabilities/skills) that loops on an open PR until every required check is green (or explicitly skipped) and every review thread is handled. The operating rules that the *runtime* skill obeys live in `SKILL.md` — that file is the product. Everything else (Python scripts, provider plugins, tests) is supporting tooling.

When modifying skill behavior, changes to `SKILL.md` are user-visible and load-bearing: they dictate how the agent actually behaves at runtime. Treat `SKILL.md` edits with the same care as code.

## Common commands

```bash
# Install dev tooling (ruff + mypy). Runtime has zero deps.
pip install -e ".[dev]"

# Run the full test suite (stdlib unittest, no pytest)
python -m unittest discover tests -v

# Run a single test file / class / method
python -m unittest tests.test_fetch_pr_checks
python -m unittest tests.test_fetch_pr_checks.TestBuildOutput.test_foo

# Lint + format check (CI runs both)
ruff check .
ruff format --check .

# Type check (configured via pyproject; just run `mypy`)
mypy

# Invoke the bundled scripts (PEP 723 inline metadata, stdlib-only)
uv run scripts/fetch_pr_checks.py [--pr N] [--skip-logs]
uv run scripts/fetch_pr_feedback.py [--pr N]
uv run scripts/watch_pr_state.py
```

CI matrix: tests on Python 3.9 / 3.11 / 3.13; lint + mypy on 3.13 only. Keep runtime code 3.9-compatible — that's why `Optional[X]` is preferred over `X | None` at module scope (ruff `UP007`/`UP045` are ignored).

## Architecture

Three layers:

1. **`SKILL.md`** — the operating contract the LLM follows at runtime. Defines run structure, exit conditions, stop-reason vocabulary, and when to consult provider docs. Not code, but authoritative.

2. **`scripts/`** — stdlib-only CLIs the skill invokes via `uv run`. They shell out to `gh` and emit structured JSON:
   - `fetch_pr_checks.py` — snapshot of CI checks + failure-log snippets + provider-tagged recovery hints.
   - `fetch_pr_feedback.py` — review threads and PR comments, classified on the [LOGAF scale](https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale).
   - `watch_pr_state.py` — stream of check-state and review events, one JSON per line, intended for Claude Code's `Monitor` tool.

   Scripts import `providers/` via a `sys.path` shim — both roots are declared in `mypy_path`.

3. **`providers/`** — pluggable provider registry. Each non-underscored `*.py` module must export a module-level `PROVIDER = Provider(...)`. `providers/__init__._discover()` auto-loads them at import time; there is no explicit registration list. A provider contributes: detection keywords, family rules, failure-marker regexes, bot-author regexes, and an optional `recovery_builder` callable that returns a `RecoveryHint`. Optional sibling `<name>.md` files are agent-facing docs that `SKILL.md` tells the runtime to read on-demand when a check carries `provider: "<name>"`.

   `_base.py` defines the `Provider` / `RecoveryHint` dataclasses. `_core.py` holds generic (non-provider-specific) bot patterns. Underscored modules are never auto-discovered.

   **Adding a provider**: drop a new `providers/<name>.py` that exports `PROVIDER`. That's the whole registration step. See `providers/README.md` for the field contract.

## Conventions that aren't obvious from the code

- Scripts are intentionally loose files, not a package. Only `providers/` is packaged (`[tool.hatch.build.targets.wheel] packages = ["providers"]`). Don't "fix" this by packaging the scripts.
- Runtime code has **zero third-party dependencies** and must stay that way — the scripts ship to end users via `uv run` with PEP 723 metadata.
- Tests use duck-typed mocks heavily; mypy's `disallow_untyped_defs` is relaxed for `tests.*`. Don't add type annotations just to silence mypy in tests.
- All skill scripts must be run from the repo root (where `.git` lives), not from the skill directory. The skill resolves its own location via `${CLAUDE_SKILL_ROOT}`.
