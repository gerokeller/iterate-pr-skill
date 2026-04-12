# iterate-pr

A [Claude Code skill](https://docs.claude.com/en/docs/claude-code/capabilities/skills) that loops on an open pull request until every required CI check is green (or explicitly skipped) and every actionable review comment has been handled.

## What it does

Each run:

1. Snapshots CI checks and review feedback from GitHub in parallel.
2. Triages actionable failures and unresolved review threads.
3. Fixes locally with minimal, targeted changes. Dedupes by root cause.
4. Replies to / resolves review threads with autonomous classification (fix / reject / blocked).
5. Pushes once at the end of the run if code changed.
6. Loops until `ready_for_merge`, `feedback_cleared`, and `all_review_threads_resolved` are all true — or until it stops with a concrete `stop_reason` and `next_action`.

Full operating rules, exit conditions, and stop-reason vocabulary live in [`SKILL.md`](./SKILL.md).

## Install

```bash
git clone https://github.com/gerokeller/iterate-pr-skill.git ~/.claude/skills/iterate-pr
```

Or symlink an existing clone:

```bash
ln -s "$PWD/iterate-pr-skill" ~/.claude/skills/iterate-pr
```

## Requirements

- [Claude Code](https://claude.com/claude-code)
- [GitHub CLI (`gh`)](https://cli.github.com/), authenticated
- [`uv`](https://docs.astral.sh/uv/) for running the bundled Python scripts

## Usage

Inside a repository with an open PR on the current branch, prompt Claude Code:

> iterate on this PR

The skill auto-loads. It will keep going through check failures and review feedback until the PR is merge-ready or it stops with a clear reason.

## Pluggable provider layer

Provider-specific handling (Supabase preview recovery, Codecov coverage blockers, bot-author detection, etc.) lives in [`providers/`](./providers/). Each provider is a small Python module plus optional agent-facing `.md` docs. The registry auto-discovers them at import time.

To add support for a new CI/preview/coverage/bot system, drop a new file into `providers/` — see [`providers/README.md`](./providers/README.md) for the interface.

## Bundled scripts

| Script | Purpose |
|--------|---------|
| `scripts/fetch_pr_checks.py` | Structured check status with failure snippets, markers, and provider-aware recovery hints |
| `scripts/fetch_pr_feedback.py` | Review feedback categorized with the [LOGAF scale](https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale) |

All scripts use PEP 723 inline metadata; invoke via `uv run <script>`.

## License

MIT
