# iterate-pr

A [Claude Code](https://claude.com/claude-code) plugin that loops on an open pull request until every required CI check is green (or explicitly skipped) and every actionable review comment has been handled.

## What it does

Each run:

1. Snapshots CI checks and review feedback from GitHub in parallel.
2. Triages actionable failures and unresolved review threads.
3. Fixes locally with minimal, targeted changes. Dedupes by root cause.
4. Replies to / resolves review threads with autonomous classification (fix / reject / blocked).
5. Pushes once at the end of the run if code changed.
6. Loops until `ready_for_merge`, `feedback_cleared`, and `all_review_threads_resolved` are all true, or until it stops with a concrete `stop_reason` and `next_action`.

Full operating rules, exit conditions, and stop-reason vocabulary live in [`skills/iterate-pr/SKILL.md`](./skills/iterate-pr/SKILL.md).

## Install

Inside Claude Code, add the marketplace and install the plugin:

```text
/plugin marketplace add gerokeller/iterate-pr-skill
/plugin install iterate-pr@iterate-pr-marketplace
```

That's it. Claude Code clones the repo into its plugin directory and the `iterate-pr` skill becomes available to the agent. No symlinks, no manual `git pull`.

To pull in a new release later:

```text
/plugin update iterate-pr@iterate-pr-marketplace
```

## Requirements

- [Claude Code](https://claude.com/claude-code)
- [GitHub CLI (`gh`)](https://cli.github.com/), authenticated (`gh auth login`)
- [`uv`](https://docs.astral.sh/uv/) for running the bundled Python scripts

## Usage

Inside a repository with an open PR on the current branch, prompt Claude Code:

> iterate on this PR

The skill auto-loads. It keeps going through check failures and review feedback until the PR is merge-ready or it stops with a clear reason.

## What a run looks like

Every time the skill stops, it emits a short verdict: a `stop_reason`, the `evidence` that produced it, and a `next_action` (unless the PR is merge-ready). You can rerun the skill after addressing the `next_action` and it will pick up from the current state.

A successful run ends with something like:

```text
stop_reason: merge-ready
evidence: ready_for_merge=true, feedback_cleared=true, all_review_threads_resolved=true, mergeStateStatus=CLEAN.
```

A blocked run ends with something like:

```text
stop_reason: blocked-by-checks
evidence: 1 check failing (tests), 0 pending, mergeStateStatus=BLOCKED, ready_for_merge=false.
next_action: inspect the failing log excerpt above; the skill attempted one fix pass and the failure persisted.
```

### Common stop reasons

| Reason | What it means | What you do |
|--------|---------------|-------------|
| `merge-ready` | CI green, all review threads resolved, no pending checks. | Merge. |
| `blocked-by-checks` | At least one check is failing, cancelled, or stuck pending. | Read the evidence, open the details link, fix or wait. |
| `blocked-by-external-check` | A third-party provider (preview env, coverage, etc.) is failing and repo-side recovery is exhausted. | Wait for the provider, or fix the provider-specific blocker named in the evidence. |
| `blocked-by-feedback` | Unresolved actionable review comments remain. | Read the threads; if the skill rejected any, its reasoning is in the reply. |
| `blocked-by-review-decision` | `reviewDecision=CHANGES_REQUESTED`. | Address the review, rerun. |
| `blocked-by-auth` | `gh auth status` failed. | `gh auth login`, rerun. |
| `blocked-by-rebase` | Branch needs rebase against the base. | Rebase, push, rerun. |
| `blocked-by-draft-pr` | PR is still a draft. | Mark ready for review or close. |
| `blocked-by-no-pr` | No PR exists for the current branch. | Open one, rerun. |
| `blocked-by-ambiguity` | A review comment depends on context the skill cannot infer. | Answer in chat; the skill continues from there. |
| `stopped-after-max-attempts` | Same failure persisted across 3 attempts. | Inspect manually and rerun once unblocked. |

Provider-contributed stop reasons like `blocked-by-supabase-preview` carry their own recovery ladder; see `skills/iterate-pr/providers/<name>.md`.

## Pluggable provider layer

Provider-specific handling (Supabase preview recovery, Codecov coverage blockers, bot-author detection, etc.) lives in [`skills/iterate-pr/providers/`](./skills/iterate-pr/providers/). Each provider is a small Python module plus optional agent-facing `.md` docs. The registry auto-discovers them at import time.

To add support for a new CI/preview/coverage/bot system, drop a new file into `skills/iterate-pr/providers/`. See [`skills/iterate-pr/providers/README.md`](./skills/iterate-pr/providers/README.md) for the interface.

## Bundled scripts

| Script | Purpose |
|--------|---------|
| `skills/iterate-pr/scripts/fetch_pr_checks.py` | Structured check status with failure snippets, markers, and provider-aware recovery hints |
| `skills/iterate-pr/scripts/fetch_pr_feedback.py` | Review feedback categorized with the [LOGAF scale](https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale) |
| `skills/iterate-pr/scripts/watch_pr_state.py` | ETag-conditional event stream of PR check transitions and new review activity, designed for Claude Code's `Monitor` tool |

All scripts use PEP 723 inline metadata; invoke via `uv run <path>`. The skill itself references them through `${CLAUDE_SKILL_DIR}/scripts/...` so paths resolve regardless of where the plugin is installed.

## Repository layout

```
.claude-plugin/
  plugin.json          # Claude Code plugin manifest
  marketplace.json     # Claude Code marketplace manifest
skills/
  iterate-pr/
    SKILL.md           # operating rules the LLM follows at runtime
    scripts/           # stdlib-only Python helpers invoked via `uv run`
    providers/         # auto-discovered CI/preview/bot plugin registry
pyproject.toml         # dev tooling (ruff + mypy); not published to PyPI
tests/                 # unittest suite
```

## Development

Install the dev tooling (ruff + mypy) once:

```bash
pip install -e ".[dev]"
```

Then:

```bash
# Unit tests (stdlib unittest)
python -m unittest discover tests -v

# Lint + format check
ruff check .
ruff format --check .

# Type check
mypy
```

CI runs all three on every PR. Tests run on Python 3.9, 3.11, and 3.13; lint and type-check run on 3.13.

## Local development against a checkout

If you're hacking on the skill itself, you don't need to install through the marketplace. Symlink the skill directory directly into Claude Code's plugin tree:

```bash
mkdir -p ~/.claude/plugins/iterate-pr-skill
ln -s "$PWD/.claude-plugin"  ~/.claude/plugins/iterate-pr-skill/.claude-plugin
ln -s "$PWD/skills"          ~/.claude/plugins/iterate-pr-skill/skills
```

Restart Claude Code and changes to `SKILL.md`, `scripts/`, or `providers/` take effect immediately, no `/plugin update` needed.

## License

MIT
