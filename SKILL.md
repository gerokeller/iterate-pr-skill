---
name: iterate-pr
description: Iterate on a PR until all required checks are green or explicitly skipped and all review feedback is handled. Use when you need to repeatedly inspect every non-green check, batch fixes locally, handle review threads and PR comments autonomously without user prompting, minimize GitHub round-trips, use parallel agents only when they provide a real speedup, push once per run, and loop until the PR is merge-ready.
---

# Iterate on a PR Until It Is Merge-Ready

Continuously iterate on the current branch until every required PR check is green or explicitly skipped and every unresolved review thread or actionable PR comment has been handled.

**Requires**: GitHub CLI (`gh`) authenticated.

**Important**: All scripts must be run from the repository root directory (where `.git` is located), not from the skill directory. Use the full path to the script via `${CLAUDE_SKILL_ROOT}`.

## Operating Rules

- Work in repeated runs. A run starts when you snapshot checks and feedback from GitHub, and ends after either one push or one no-code review-only pass.
- At the start of each run, record the `snapshot_at` values from the check and feedback scripts. Use them as the baseline for stale-state and reopen detection.
- Optimize for low-latency runs: prefer one fast initial snapshot, one optional enrichment refresh, and one post-push refresh. Do not repeatedly poll or re-fetch the same data without a concrete reason.
- Do not ask the user to choose which review comments to address during a normal run. The skill is responsible for deciding `fix`, `reject`, or `defer because blocked`.
- In each run, inspect all PR checks first and identify every check that is not `pass` or `skipping`.
- Treat check states as:
  - success: `pass`, `skipping`
  - actionable failure: `fail`, `cancel`
  - waiting: `pending`
- Treat all failing checks and status contexts as blockers, including external providers such as Supabase, Vercel, Codacy, or other non-GitHub Actions integrations.
- Do not classify Supabase Preview failures as ignorable infrastructure. Treat Supabase checks as actionable until you have inspected the exact failure output and exhausted the Supabase recovery ladder below.
- Never declare a PR merge-ready while any check or status context is `fail`, `cancel`, or `pending`, even if you believe the failure is stale, infrastructural, or unrelated to code. In that case the outcome is `blocked`, not `complete`.
- In parallel with CI triage, inspect unresolved review feedback and handle review threads and actionable PR comments one by one.
- Treat resolved review threads as necessary but not sufficient. A PR is not feedback-complete while any review thread remains unresolved, or while top-level review submissions, issue comments, or a `CHANGES_REQUESTED` review decision still require action.
- Keep all fixes for the current run local. Do not push mid-run.
- Deduplicate overlapping failures and comments by root cause. One fix may close several failing checks and feedback items.
- Cache decisions within the run. Once a root cause group or review item has been classified, reuse that decision unless new GitHub activity invalidates it.
- For review threads, do not resolve immediately after editing. First finish the local fix, validate it, re-fetch feedback if needed to confirm the thread is still unresolved, then reply if useful and resolve.
- When performing GitHub mutations such as replying, resolving, or re-fetching watch state, retry transient failures up to 3 times with short backoff before treating the operation as blocked.
- For non-thread PR comments, reply after deciding to fix or reject. They are not resolvable.
- Use agent teams when there are multiple independent work items and the environment supports parallel agents. Keep one orchestrator agent responsible for the run, and use side agents only for bounded analysis or disjoint implementation work.
- Use fast paths aggressively:
  - if the initial check snapshot shows no actionable checks, do not pay for failed-log fetches
  - if the run makes no code changes, skip push-related waiting
  - if only one root cause group exists, stay single-agent
- Every time the skill stops, it must report a clear `stop_reason` with concrete evidence. Never end with only “done”, “complete”, or “ready” without explaining why the loop ended.
- Push exactly once at the end of the run if code changed, after all fixes and thread decisions for that run are complete.
- If a run only adds replies or resolves threads and produces no code changes, do not create an empty commit and do not push.
- After pushing, restart from the beginning: fetch checks again, fetch feedback again, and continue until no unresolved review comments remain and all checks are green or skipped.

## Bundled Scripts

### `scripts/fetch_pr_checks.py`

Fetches CI check status and extracts failure snippets from logs. The output distinguishes `cancel` from `skipping` so the agent can treat canceled checks as actionable.

```bash
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_checks.py [--pr NUMBER]
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_checks.py --skip-logs [--pr NUMBER]
```

Use `--skip-logs` for the fast initial snapshot. Re-run without `--skip-logs` only when the summary shows actionable failures and you need log detail.

Returns JSON:
```json
{
  "pr": {"number": 123, "branch": "feat/foo"},
  "snapshot_at": "2026-03-15T10:00:00+00:00",
  "logs_included": true,
  "summary": {"total": 5, "passed": 3, "failed": 1, "cancelled": 1, "pending": 0, "skipped": 0, "actionable": 2},
  "completion_blockers": ["One or more checks are still failing, pending, or cancelled", "GitHub mergeStateStatus is BLOCKED"],
  "ready_for_merge": false,
  "checks": [
    {"name": "tests", "status": "fail", "check_type": "github-actions", "provider": "github-actions", "is_actionable": true, "log_snippet": "...", "run_id": 123, "job_id": 456},
    {"name": "Configure Supabase Preview", "status": "fail", "provider": "supabase", "check_family": "supabase-preview", "failure_markers": ["MIGRATIONS_FAILED"], "recovery_hint": {"classification": "supabase-preview"}},
    {"name": "deploy", "status": "cancel", "is_actionable": true},
    {"name": "lint", "status": "pass"}
  ]
}
```

### `scripts/fetch_pr_feedback.py`

Fetches and categorizes PR review feedback using the [LOGAF scale](https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale). Items include `source`, stable IDs, timestamps, and review-thread metadata so the agent can reply and resolve deterministically.

```bash
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_feedback.py [--pr NUMBER]
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_feedback.py --skip-issue-comments [--pr NUMBER]
```

Use `--skip-issue-comments` for the fast initial snapshot. Re-run without it before replying, resolving, or declaring the PR clean.

Returns JSON with feedback categorized as:
- `high` - Must address before merge (`h:`, blocker, changes requested)
- `medium` - Should address (`m:`, standard feedback)
- `low` - Optional (`l:`, nit, style, suggestion)
- `bot` - Automated comments (Codecov, Sentry, etc.)
- `resolved` - Already resolved threads

When available, use `snapshot_at`, `latest_activity_at`, and `thread_comment_count` to detect that a thread changed after the run began.
Use `issue_comments_included` and `completion_requires_full_fetch` to know whether the snapshot is safe for completion decisions.
Use `completion_blockers`, `feedback_cleared`, `unresolved_review_threads`, and `all_review_threads_resolved` as the authoritative feedback gate summary.

## Workflow

### 0. Verify GitHub Access

Before starting the loop, verify GitHub CLI authentication:

```bash
gh auth status
```

If authentication is broken or expired, stop and fix that first. Do not begin iteration with a partially working `gh` session.

### 1. Identify PR

```bash
gh pr view --json number,url,headRefName
```

Stop if no PR exists for the current branch.

### 2. Start a Run by Snapshotting Current State

Fetch both CI and feedback state in parallel before making changes:

```bash
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_checks.py --skip-logs [--pr NUMBER]
uv run ${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_feedback.py --skip-issue-comments [--pr NUMBER]
```

Treat these as the authoritative starting point for the current run.

Fast-path rules:
- if `summary.actionable == 0`, keep the fast check snapshot and do not refetch logs
- if there are actionable failures, rerun `fetch_pr_checks.py` without `--skip-logs` once to enrich the current run with failure details
- use the partial feedback snapshot for planning and triage
- rerun `fetch_pr_feedback.py` without `--skip-issue-comments` only before the reply/resolve phase, or before declaring the run clean
- do not re-run the check script again until either a push happens or the current snapshot is stale enough that it may be wrong
- do not re-run the full feedback fetch multiple times in the same run unless new reviewer activity makes the snapshot unsafe

Hard gate:
- use `completion_blockers` and `ready_for_merge` from `fetch_pr_checks.py` as the authoritative merge gate summary
- do not override `ready_for_merge: false` with personal judgment about whether a failing check is “real”
- do not infer that a failing check is optional, informational, or non-required from its provider name, missing workflow name, or status-context shape
- never say “all required checks pass” unless `summary.failed == 0`, `summary.cancelled == 0`, `summary.pending == 0`, and `ready_for_merge == true`
- if a check is externally broken or stale, inspect the details URL and any provider-specific recovery path before reporting `blocked by external check`
- use `completion_blockers` and `feedback_cleared` from `fetch_pr_feedback.py` as the authoritative feedback gate summary
- require `all_review_threads_resolved` before the PR can be considered feedback-complete
- do not treat “all threads resolved” as success if top-level review comments or review submissions still require action

If a run is interrupted by new reviewer activity or changing check state, do not guess. Re-fetch both snapshots and continue from the newest state.

### 3. Triage All PR Checks First

Run `${CLAUDE_SKILL_ROOT}/scripts/fetch_pr_checks.py` to get structured failure data.

For this run:
- enumerate every check whose status is not `pass` or `skipping`
- separate them into:
  - failing or canceled checks you can act on now
  - pending/in-progress checks that require waiting
- do not stop after the first failing check; gather the full failing set for the run

If the same check keeps flapping between `pending` and terminal states, prefer waiting for a stable terminal state before making more edits unless a different check already gives a concrete actionable failure.

**Wait before acting only when blocked by pending state:** If checks are still `pending`, especially bot-related checks (`sentry`, `codecov`, `cursor`, `bugbot`, `seer`), wait for them to finish before concluding the run because they may produce more failures or comments.

Avoid expensive log work:
- read each unique failed workflow log once per run
- group failing checks by likely root cause before deeper inspection
- do not fetch or inspect more log detail after the root cause is already clear

Supabase-specific handling:
- treat `Ensure Supabase Preview Branch`, `Configure Supabase Preview`, and `Supabase Preview` as one Supabase root-cause group when they fail together
- use `provider`, `check_family`, `failure_markers`, `run_id`, `job_id`, `link`, and `recovery_hint` from `fetch_pr_checks.py` when present
- if a Supabase-related check failed, inspect the exact Preview workflow job output or the status details URL before deciding whether the problem is code, migrations, configuration, or stale preview state
- if logs point to migrations, schema drift, or preview configuration, fix the repository issue locally and validate the relevant migration or test surface before pushing
- if logs or status details indicate stale or stuck preview provisioning, run this recovery ladder before stopping:
  1. rerun the Preview workflow once with `gh run rerun RUN_ID`
  2. wait for the rerun to settle, then snapshot checks again
  3. if the failure still points to stale preview state, close and reopen the PR once so the `reopened` event recreates preview provisioning
  4. snapshot checks again and continue the loop
- if only the external `Supabase Preview` status context is failing, inspect its details URL and pair it with the latest `Preview` workflow run instead of assuming it is untouchable
- do not repeat the same Supabase recovery step more than once in a single iteration session unless new evidence appears
- only report `blocked-by-external-check` or `blocked-by-supabase-preview` for Supabase after the failure output was inspected and the recovery ladder was exhausted

Codecov-specific handling:
- treat `codecov/patch` and other failing Codecov contexts as blockers while `ready_for_merge` is false
- use the Codecov `detailsUrl` and `recovery_hint` to determine whether the failure is caused by low patch coverage, low project coverage, or upload/config issues
- if Codecov reports low coverage, identify the changed lines reducing coverage and add or update tests locally before pushing
- do not describe a failing Codecov check as informational, optional, or safe to ignore unless GitHub explicitly reports the PR as merge-ready after the check settles

### 3.5. Launch Parallel Work When It Helps

If the environment supports agent teams and the run contains independent work, parallelize it.

Default team shape:
- main agent: owns the run plan, batching decisions, validation, commit, push, replies, and thread resolution
- analysis agent: maps failing checks to likely root causes, groups duplicates, and summarizes affected files
- review agent: classifies comments as `fix`, `reject`, or `blocked`, and drafts concise reply text
- implementation agents: fix disjoint file groups when multiple independent changes are needed

Rules:
- spawn side agents only when the expected savings exceed the coordination cost
- prefer at most 2 or 3 side agents in a normal run
- only parallelize work that does not require the immediate next step to wait on the result
- give implementation agents disjoint write scopes
- do not let side agents push, resolve threads, or make final merge-readiness decisions
- integrate all side-agent output into one local batch for the run before pushing
- if only one clear root cause exists, stay single-agent and keep the overhead low

Good triggers for parallel work:
- 2 or more independent root cause groups across different files or packages
- 1 check-failure group plus 4 or more actionable review items in different areas
- a long-running local validation can proceed while review classification or reply drafting happens separately

Avoid parallel work when:
- there is only one obvious fix path
- the run is small enough that coordination overhead dominates
- multiple candidate changes touch the same files or same tight codepath

### 4. Fix All Actionable Check Failures Locally

For each failing check in the current run:
1. Read the `log_snippet` to understand the failure
2. Read the relevant code before making changes
3. Fix the issue with minimal, targeted changes

Do NOT assume what failed based on check name alone. Always read logs first.

When multiple failing checks point to the same root cause, make one coherent fix that clears the whole group.

Before editing, write a short root-cause summary for yourself when more than one actionable check fails. Use that summary to avoid symptom-by-symptom patching.

Prefer the cheapest sufficient validation:
- file- or package-scoped validation first
- workflow-level validation second
- full-suite validation only when the run changed shared infrastructure, core contracts, or multiple root-cause groups

### 5. In Parallel, Process Review Feedback One Item at a Time

Use the feedback snapshot from step 2. Focus on unresolved review threads and actionable conversation comments.

For speed, the initial feedback snapshot may exclude top-level PR comments. That is acceptable for planning, but not for completion. Before final mutation or success decisions, upgrade to a full feedback fetch for the current run.

Never stop to ask the user which comment to handle unless the run is truly blocked by missing business context, missing credentials, or mutually exclusive product decisions that cannot be inferred from code, tests, or prior comments.

Classify first, mutate later:
- first classify all actionable comments for the run
- then make the code changes
- then upgrade to a full feedback fetch if the current snapshot skipped issue comments
- then perform one reply/resolve phase near the end of the run
- do not interleave comment mutations with active code editing unless a live thread state change forces it

Process feedback in this order:
1. `high`
2. `medium`
3. `low`

Rules:
- `high`: always address in the current run
- `medium`: always address in the current run
- `low`: auto-fix only when behavior is unchanged and scope is local; otherwise reject with a concise rationale
- `bot`: informational only unless they imply a concrete failing check
- `resolved`: ignore

Autonomous decision policy:
- choose `fix` for correctness issues, failing tests, typing/lint problems, broken edge cases, missing validation, clear readability wins with local scope, and reviewer requests that align with existing architecture
- choose `reject` for pure preference comments, speculative refactors, broad style churn, out-of-scope product changes, or suggestions that conflict with established patterns in the touched code
- choose the smallest safe fix when multiple fixes are possible
- if a comment is ambiguous, prefer a conservative local fix if one is obvious; otherwise reject with a concise technical rationale instead of asking the user
- only mark `blocked` when the comment depends on unknown business requirements, unavailable credentials, external service state, or conflicting reviewer instructions that cannot be resolved from repository context

Reply style for rejected comments:
- brief and technical
- explain why the current approach is kept
- mention scope, compatibility, or consistency with existing patterns when relevant
- do not argue at length

For each unresolved review thread:
1. Read the comment and surrounding code
2. Decide `fix`, `reject`, or `blocked`
3. If `fix`, implement the change locally
4. Validate the local fix, or confirm the rejection rationale
5. Re-fetch feedback only if the run has been long, new reviewer activity is likely, or the feedback snapshot is stale enough to be unsafe; then confirm the thread is still unresolved and has not gained newer activity than the run baseline
6. If `reject`, reply on the thread with a concise technical reason
7. If `fix`, optionally reply with a concise note pointing to the local batch
8. Resolve the thread unless the item is truly blocked

For blocked items:
- stop only after exhausting repository context, logs, prior comments, and available local evidence
- summarize exactly what is missing
- do not resolve the thread
- treat the blocked item as the reason the run cannot complete

If a resolved thread reopens, or a new thread/comment appears on the same area after the run baseline, treat it as new work in the next pass instead of folding it into an old decision.

Resolve a review thread with GraphQL:

```bash
gh api graphql \
  -f query='mutation($threadId: ID!) { resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } } }' \
  -F threadId=THREAD_ID
```

Reply before resolving when rejecting, or when a short explanation is useful:

```bash
gh api graphql \
  -f query='mutation($pullRequestReviewThreadId: ID!, $body: String!) { addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $pullRequestReviewThreadId, body: $body}) { comment { url } } }' \
  -F pullRequestReviewThreadId=THREAD_ID \
  -F body='Implemented in the latest local batch.' 
```

If a comment is not part of a review thread and cannot be resolved, still reply after deciding to fix or reject. Use the `comment_id`, `url`, and `source` from `fetch_pr_feedback.py` to target the right item. Do not attempt to resolve non-thread comments.

For GitHub mutations:
- retry up to 3 times on transient API or network errors
- use a short backoff between retries
- if the operation still fails, stop the loop and surface the blocker instead of assuming success
- batch the mutation phase near the end of the run so replies and resolutions happen with fresh context and fewer GitHub round-trips
- never reply, resolve, or declare success from a partial feedback snapshot that skipped issue comments
- never declare success from a feedback snapshot where `feedback_cleared` is false
- never declare success while `all_review_threads_resolved` is false

### 6. Keep a Single Local Batch per Run

Do not push while handling individual failures or comments.

Before pushing, verify the full local batch:
- review the diff
- run the narrowest local validation that covers each touched failure first
- if the run touched multiple concerns or shared codepaths, run broader validation before push
- ensure every failing check and every chosen feedback item from this run has been handled
- ensure every autonomous `reject` has a reply if the comment is still open and reply-capable
- avoid redundant validation passes once a root cause group is already covered by a stronger later validation

### 7. Commit Once and Push Once per Run

Create one or more local commits as needed for the current run, but do not push until the run is complete.

```bash
git add <files>
git commit -m "fix: <descriptive message>"
git push
```

Rules:
- if code changed, commit locally and push once
- if no code changed, do not create an empty commit
- comment replies and review-thread resolution alone do not require a push
- do not start a second code batch in the same run after pushing; the push ends the run

### 8. Recheck From the Top

After pushing, or after completing a no-code review-only run, return to step 2. Do not assume the PR is done based on local state.

If the push triggered new checks, wait for GitHub to report them:

```bash
gh pr checks --watch --interval 30
```

Then fetch checks and feedback again and start the next run.

If the run had no code changes, skip `gh pr checks --watch` because no new CI work was triggered.

### 9. Make the Final Verdict

Before saying the PR is complete, merge-ready, or safe to merge:
- run the final check snapshot and inspect `completion_blockers` and `ready_for_merge`
- run the final full feedback snapshot and inspect `completion_blockers`, `feedback_cleared`, `unresolved_review_threads`, and `all_review_threads_resolved`
- confirm the PR is not draft and GitHub `mergeStateStatus` is in a clean state

Allowed final outcomes:
- `merge-ready`: `ready_for_merge` is true, `feedback_cleared` is true, and `all_review_threads_resolved` is true
- `blocked`: any `completion_blockers` remain, including external or infrastructure failures

Do not say “merge-ready” when the actual outcome is “blocked by failing external checks” or “blocked by remaining review feedback.”
Do not say “all required checks pass” when any check or status context is still failing, cancelled, or pending.

### 10. Report Why the Loop Stopped

Whenever the skill finishes a run or stops the overall loop, the final message must include:
- `stop_reason`: one short reason label
- `evidence`: the concrete facts that caused the stop
- `next_action`: what should happen next, unless the stop reason is `merge-ready`

Preferred `stop_reason` values:
- `merge-ready`
- `blocked-by-checks`
- `blocked-by-feedback`
- `blocked-by-external-check`
- `blocked-by-supabase-preview`
- `blocked-by-review-decision`
- `blocked-by-draft-pr`
- `blocked-by-no-pr`
- `blocked-by-auth`
- `blocked-by-rebase`
- `blocked-by-ambiguity`
- `stopped-after-max-attempts`

Evidence rules:
- if checks are blocking, name the failing or pending checks and include `mergeStateStatus`
- if feedback is blocking, include `reviewDecision`, actionable feedback counts, unresolved review-thread counts, and whether unresolved top-level comments or review submissions remain
- if the stop is due to external infrastructure, name the external provider and the failing check/context, include the details URL when available, and list the recovery actions already attempted
- if the stop is due to Supabase, include the failing Supabase checks, any extracted failure markers such as `MIGRATIONS_FAILED`, and whether Preview rerun / PR reopen recovery was attempted
- if the stop is success, say explicitly that `ready_for_merge` is true, `feedback_cleared` is true, and `all_review_threads_resolved` is true

Minimum final-output shape:
- `stop_reason: ...`
- `evidence: ...`
- `next_action: ...`

Examples:
- `stop_reason: merge-ready`
  `evidence: ready_for_merge=true, feedback_cleared=true, all_review_threads_resolved=true, mergeStateStatus=CLEAN, no actionable feedback remains.`
- `stop_reason: blocked-by-external-check`
  `evidence: Vercel Preview Comments is still failing after inspecting its details URL and exhausting the available retry path; mergeStateStatus=BLOCKED, ready_for_merge=false.`
  `next_action: wait for the provider issue to clear or fix the provider-specific blocker, then rerun iterate-pr.`
- `stop_reason: blocked-by-supabase-preview`
  `evidence: Configure Supabase Preview and Supabase Preview are failing, failure_markers=[MIGRATIONS_FAILED,TIMEOUT_WAITING_FOR_BRANCH], mergeStateStatus=BLOCKED, Preview rerun attempted=true, PR reopen attempted=true.`
  `next_action: inspect the failing preview branch state in Supabase or fix the migration/config issue indicated by the logs, then rerun iterate-pr.`
- `stop_reason: blocked-by-feedback`
  `evidence: reviewDecision=CHANGES_REQUESTED, actionable_items=4, unresolved_review_threads=2, feedback_cleared=false.`
  `next_action: address the remaining review feedback and rerun iterate-pr.`

## Exit Conditions

**Success:** `ready_for_merge` is true, `feedback_cleared` is true, `all_review_threads_resolved` is true, all PR checks and status contexts are `pass` or `skipping`, and there are no unresolved actionable review comments, top-level review submissions, or review threads.

**Ask for help:** Same failure after 3 attempts, review feedback is ambiguous, rejection would be contentious, or a provider-specific recovery ladder has been exhausted and checks are still blocking merge readiness.

**Stop:** No PR exists, branch needs rebase.

## Fallback

If scripts fail, use `gh` CLI directly:
- `gh pr checks --json name,state,bucket,link`
- `gh run view <run-id> --log-failed`
- `gh api repos/{owner}/{repo}/pulls/{number}/comments`
- `gh api graphql` for `reviewThreads`, `addPullRequestReviewThreadReply`, and `resolveReviewThread`
