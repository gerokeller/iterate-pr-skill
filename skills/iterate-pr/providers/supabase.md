# Supabase

Load this doc when a failing check carries `provider: "supabase"` or `check_family: "supabase-preview"`.

## Root-cause grouping

Treat `Ensure Supabase Preview Branch`, `Configure Supabase Preview`, and `Supabase Preview` as **one** root-cause group when they fail together. One fix usually clears all three.

Use `provider`, `check_family`, `failure_markers`, `run_id`, `job_id`, `link`, and `recovery_hint` from `fetch_pr_checks.py` when present.

## Recovery ladder

1. Inspect the exact Preview workflow job output or the status details URL before deciding whether the problem is code, migrations, configuration, or stale preview state.
2. If logs point to migrations, schema drift, or preview configuration, fix the repository issue locally and validate the relevant migration or test surface before pushing.
3. If logs or status details indicate stale or stuck preview provisioning:
   1. Rerun the Preview workflow once with `gh run rerun <RUN_ID>`.
   2. Wait for the rerun to settle, then snapshot checks again.
   3. If the failure still points to stale preview state, close and reopen the PR once so the `reopened` event recreates preview provisioning.
   4. Snapshot checks again and continue the loop.
4. If only the external `Supabase Preview` status context is failing, inspect its details URL and pair it with the latest `Preview` workflow run rather than assuming it is untouchable.

Do not repeat the same recovery step more than once in a single iteration session unless new evidence appears.

## Failure markers

Extracted automatically from job logs when present:

| Marker | Meaning |
|--------|---------|
| `MIGRATIONS_FAILED` | Preview applied the migration set and a statement failed. Real repo issue until proven stale. |
| `TIMEOUT_WAITING_FOR_BRANCH` | Preview branch provisioning never became ready. Usually stale preview state. |
| `FAILED_TO_SET_SECRETS` | Secret propagation to the preview branch failed. Infra blip; rerun is often enough. |
| `AUTH_HOOK_CONFIGURATION_FAILED` | Preview's auth hook wiring failed. Usually a config mismatch; inspect logs. |
| `FAILED_TO_CREATE_SUPABASE_BRANCH` | Branch creation API call failed. Transient; rerun first. |
| `FAILED_TO_LIST_SUPABASE_BRANCHES` | Preview workflow cannot enumerate branches. Usually auth/transient. |

## Stop reason

Only report `blocked-by-supabase-preview` after the failure output was inspected and the recovery ladder was exhausted. Never use it as a shortcut to skip inspection.

### Evidence format

```
stop_reason: blocked-by-supabase-preview
evidence: Configure Supabase Preview and Supabase Preview are failing,
  failure_markers=[MIGRATIONS_FAILED,TIMEOUT_WAITING_FOR_BRANCH],
  mergeStateStatus=BLOCKED,
  Preview rerun attempted=true,
  PR reopen attempted=true.
next_action: inspect the failing preview branch state in Supabase or fix the migration/config issue indicated by the logs, then rerun iterate-pr.
```
