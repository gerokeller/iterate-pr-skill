# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A [Claude Code plugin](https://docs.claude.com/en/docs/claude-code/plugins) shipping a single skill (`iterate-pr`) that loops on an open PR until every required check is green (or explicitly skipped) and every review thread is handled. The operating rules the *runtime* skill obeys live in `skills/iterate-pr/SKILL.md`. That file is the product. Everything else (Python scripts, provider plugins, tests) is supporting tooling.

When modifying skill behavior, changes to `SKILL.md` are user-visible and load-bearing: they dictate how the agent actually behaves at runtime. Treat `SKILL.md` edits with the same care as code.

## Repository layout

```
.claude-plugin/
  plugin.json            # Claude Code plugin manifest (keep version in sync with pyproject)
  marketplace.json       # one-plugin marketplace served from this same repo
skills/
  iterate-pr/
    SKILL.md             # runtime operating contract
    scripts/             # stdlib-only Python helpers invoked via `uv run`
    providers/           # auto-discovered CI/preview/bot plugin registry
pyproject.toml           # dev tooling (ruff + mypy); not published to PyPI
tests/                   # unittest suite, sys.path-shimmed to point inside skills/iterate-pr/
```

The `skills/iterate-pr/` prefix matters: Claude Code's plugin loader resolves `${CLAUDE_SKILL_ROOT}` to the skill's own directory, not the plugin root. SKILL.md invocations like `uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_checks.py` only work because `scripts/` and `providers/` live as siblings of SKILL.md inside the skill dir.

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
uv run skills/iterate-pr/scripts/fetch_pr_checks.py [--pr N] [--skip-logs]
uv run skills/iterate-pr/scripts/fetch_pr_feedback.py [--pr N]
uv run skills/iterate-pr/scripts/watch_pr_state.py [--pr N --repo OWNER/NAME]
```

CI matrix: tests on Python 3.9 / 3.11 / 3.13; lint + mypy on 3.13 only. Keep runtime code 3.9-compatible — that's why `Optional[X]` is preferred over `X | None` at module scope (ruff `UP007`/`UP045` are ignored).

## Architecture

Three layers, all under `skills/iterate-pr/`:

1. **`SKILL.md`** — the operating contract the LLM follows at runtime. Defines run structure, exit conditions, stop-reason vocabulary, and when to consult provider docs. Not code, but authoritative.

2. **`scripts/`** — stdlib-only CLIs the skill invokes via `uv run`. They shell out to `gh` and emit structured JSON:
   - `fetch_pr_checks.py` — snapshot of CI checks + failure-log snippets + provider-tagged recovery hints.
   - `fetch_pr_feedback.py` — review threads and PR comments, classified on the [LOGAF scale](https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale).
   - `watch_pr_state.py` — stream of check-state and review events, one JSON per line, intended for Claude Code's `Monitor` tool. Always pass `--pr` and `--repo` when launching via Monitor; the subprocess inherits the parent's cwd, which may not be the PR's worktree.

   Scripts import `providers/` via a `sys.path` shim. Both roots are declared in `mypy_path`.

3. **`providers/`** — pluggable provider registry. Each non-underscored `*.py` module must export a module-level `PROVIDER = Provider(...)`. `providers/__init__._discover()` auto-loads them at import time; there is no explicit registration list. A provider contributes detection keywords, family rules, failure-marker regexes, bot-author regexes, and an optional `recovery_builder` callable that returns a `RecoveryHint`. Optional sibling `<name>.md` files are agent-facing docs that `SKILL.md` tells the runtime to read on-demand when a check carries `provider: "<name>"`.

   `_base.py` defines the `Provider` / `RecoveryHint` dataclasses. `_core.py` holds generic (non-provider-specific) bot patterns. Underscored modules are never auto-discovered.

   **Adding a provider**: drop a new `skills/iterate-pr/providers/<name>.py` that exports `PROVIDER`. That's the whole registration step. See `skills/iterate-pr/providers/README.md` for the field contract.

## Conventions that aren't obvious from the code

- Scripts are intentionally loose files, not a package. `pyproject.toml` packages `providers/` only via a hatch `sources` mapping that flattens `skills/iterate-pr/providers` to `providers` in the wheel — that exists solely so `pip install -e ".[dev]"` works in CI. Don't "fix" this by packaging the scripts.
- Runtime code has **zero third-party dependencies** and must stay that way. Scripts ship to end users via `uv run` with PEP 723 metadata.
- Tests use duck-typed mocks heavily; mypy's `disallow_untyped_defs` is relaxed for `tests.*`. Don't add type annotations just to silence mypy in tests.
- The plugin version in `.claude-plugin/plugin.json` and the wheel version in `pyproject.toml` must stay in sync. Claude Code uses the `plugin.json` version for `/plugin update` detection. See the **Releases** section below for how bumps happen.
- All skill scripts must be run from the consumer's repo root (where their `.git` lives), not from the skill directory. The skill resolves its own location via `${CLAUDE_SKILL_ROOT}`.

## Releases

**The version bump is manual; the release itself is automatic.** Merging to `master` does not, by itself, ship a new version, but any merge that changes the `version` field will be tagged and published automatically.

`.github/workflows/release.yml` runs on every push to `master`:

1. Reads `version` from `.claude-plugin/plugin.json`.
2. If a git tag `v<version>` already exists, it exits as a no-op.
3. Otherwise, it creates tag `v<version>` at the current commit and publishes a GitHub Release with auto-generated notes.

The workflow never writes back to the repo and never auto-bumps. So a release happens exactly when (and only when) a merged PR changed the version field. This keeps the workflow compatible with branch rulesets that require CodeQL scanning before push, and makes every release a deliberate act without requiring any post-merge steps.

### How to cut a release

In the PR that should ship the new version (typically the final PR of a batch, or a dedicated release PR), edit both files so they agree:

- `.claude-plugin/plugin.json`: `"version": "X.Y.Z"`
- `pyproject.toml`: `version = "X.Y.Z"`

Follow semver:
- **patch** (`0.2.0` → `0.2.1`) for bug fixes and backwards-compatible internals
- **minor** (`0.2.0` → `0.3.0`) for new features, new providers, new scripts
- **major** (`0.2.0` → `1.0.0`) for breaking changes to `SKILL.md` behavior, script CLIs, or provider contracts

On merge, the workflow tags that commit and publishes the Release. No further action required.

### Rules for contributors and AI agents

- **Never bump the version in a PR that is not the release PR.** If you are fixing a bug or adding a small feature, leave the version untouched; the release PR batches multiple changes into one version bump.
- **Do not create git tags or GitHub Releases by hand.** The workflow owns tag creation, and a manual tag will silence the workflow (it will see the tag and exit as a no-op for that version).
- **Changes that should not ship at all** (e.g. CI-only tweaks, README typos) can be merged without a version bump; the workflow will see the existing tag and do nothing.
- **If the workflow fails**, fix it and merge the fix before the next release. A failed release run does not retry automatically. You can also re-run the failed workflow manually from the Actions tab once the underlying issue is resolved, since the tag-existence check is idempotent.
