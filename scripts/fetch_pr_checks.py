#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""
Fetch PR CI checks and extract relevant failure snippets.

Usage:
    python fetch_pr_checks.py [--pr PR_NUMBER]

If --pr is not specified, uses the PR for the current branch.

Output: JSON to stdout with structured check data.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from providers import (
    all_failure_markers,
)
from providers import (
    build_recovery_hint as provider_recovery_hint,
)
from providers import (
    classify_family as provider_classify_family,
)
from providers import (
    detect_provider as provider_detect,
)

ACTIONS_RUN_LINK_RE = re.compile(r"/actions/runs/(?P<run_id>\d+)(?:/job/(?P<job_id>\d+))?")
FAILURE_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(all_failure_markers())


def run_gh(args: list[str]) -> dict[str, Any] | list[Any] | None:
    """Run a gh CLI command and return parsed JSON output."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None
    except subprocess.CalledProcessError as e:
        print(f"Error running gh {' '.join(args)}: {e.stderr}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        return None


def get_pr_info(pr_number: int | None = None) -> dict[str, Any] | None:
    """Get PR info, optionally by number or for current branch."""
    args = [
        "pr",
        "view",
        "--json",
        "number,url,headRefName,baseRefName,mergeStateStatus,reviewDecision,isDraft",
    ]
    if pr_number:
        args.insert(2, str(pr_number))
    result = run_gh(args)
    return result if isinstance(result, dict) else None


def get_checks(pr_number: int | None = None) -> list[dict[str, Any]]:
    """Get all checks for a PR."""
    args = ["pr", "checks", "--json", "name,state,bucket,link,workflow,event"]
    if pr_number:
        args.insert(2, str(pr_number))
    result = run_gh(args)
    return result if isinstance(result, list) else []


def get_failed_runs(branch: str) -> list[dict[str, Any]]:
    """Get recent failed or cancelled workflow runs for a branch."""
    result = run_gh(
        [
            "run",
            "list",
            "--branch",
            branch,
            "--limit",
            "10",
            "--json",
            "databaseId,name,status,conclusion,headSha",
        ]
    )
    if not isinstance(result, list):
        return []
    # Return runs that failed or were cancelled.
    return [r for r in result if r.get("conclusion") in {"failure", "cancelled"}]


def parse_actions_run_ids(link: str) -> tuple[int | None, int | None]:
    """Extract run and job identifiers from a GitHub Actions job URL."""
    match = ACTIONS_RUN_LINK_RE.search(link)
    if not match:
        return None, None

    run_id = int(match.group("run_id"))
    job_id = match.group("job_id")
    return run_id, int(job_id) if job_id else None


def detect_check_type(link: str, workflow: str) -> str:
    """Classify whether the check comes from GitHub Actions or an external status context."""
    if "/actions/runs/" in link.lower() or workflow:
        return "github-actions"
    return "status-context"


def detect_provider(name: str, workflow: str, link: str) -> str:
    """Infer the provider behind a check or status context.

    Provider-specific detection is delegated to the pluggable :mod:`providers`
    registry. If no provider matches, fall back to "github-actions" for jobs
    that originate from an Actions run URL and "external" for everything else.
    """
    match = provider_detect(name, workflow, link)
    if match:
        return match
    if detect_check_type(link, workflow) == "github-actions":
        return "github-actions"
    return "external"


def detect_check_family(name: str, workflow: str, link: str) -> str | None:
    """Group related checks into a provider-specific family via the registry."""
    provider = provider_detect(name, workflow, link)
    if not provider:
        return None
    return provider_classify_family(provider, name, workflow, link)


def extract_failure_snippet(log_text: str, max_lines: int = 50) -> str:
    """Extract relevant failure snippet from log text.

    Looks for common failure markers and extracts surrounding context.
    """
    lines = log_text.split("\n")

    # Patterns that indicate failure points (case-insensitive via re.IGNORECASE)
    failure_patterns = [
        r"error[:\s]",
        r"failed[:\s]",
        r"failure[:\s]",
        r"traceback",
        r"exception",
        r"assert(ion)?.*failed",
        r"FAILED",
        r"panic:",
        r"fatal:",
        r"npm ERR!",
        r"yarn error",
        r"ModuleNotFoundError",
        r"ImportError",
        r"SyntaxError",
        r"TypeError",
        r"ValueError",
        r"KeyError",
        r"AttributeError",
        r"NameError",
        r"IndentationError",
        r"===.*FAILURES.*===",
        r"___.*___",  # pytest failure separators
    ]

    combined_pattern = "|".join(failure_patterns)

    # Find lines matching failure patterns
    failure_indices = []
    for i, line in enumerate(lines):
        if re.search(combined_pattern, line, re.IGNORECASE):
            failure_indices.append(i)

    if not failure_indices:
        # No clear failure point, return last N lines
        return "\n".join(lines[-max_lines:])

    # Extract context around first failure point
    # Include some context before and after
    first_failure = failure_indices[0]
    start = max(0, first_failure - 5)
    end = min(len(lines), first_failure + max_lines - 5)

    snippet_lines = lines[start:end]

    # If there are more failures after our snippet, note it
    remaining_failures = [i for i in failure_indices if i >= end]
    if remaining_failures:
        snippet_lines.append(f"\n... ({len(remaining_failures)} more error(s) follow)")

    return "\n".join(snippet_lines)


def extract_failure_markers(log_text: str) -> list[str]:
    """Return stable failure markers extracted from raw job logs."""
    markers: list[str] = []
    for label, pattern in FAILURE_MARKER_PATTERNS:
        if pattern.search(log_text):
            markers.append(label)
    return markers


def build_recovery_hint(check: dict[str, Any]) -> dict[str, Any] | None:
    """Attach provider-specific next steps for actionable checks.

    Provider-specific recovery logic is delegated to the :mod:`providers`
    registry. A generic fallback covers non-GitHub-Actions status contexts
    that no provider claimed.
    """
    status = check.get("status", "")
    provider = check.get("provider")
    family = check.get("check_family")
    check_type = check.get("check_type")
    failure_markers = check.get("failure_markers", [])

    hint = provider_recovery_hint(provider, family, status, failure_markers)
    if hint is not None:
        return hint

    if check_type == "status-context" and status in {"fail", "cancel", "pending"}:
        return {
            "classification": "external-status",
            "summary": "Inspect the details URL and any paired workflow checks before treating this as an untouchable external blocker.",
            "recommended_steps": [
                "Open the details URL and capture the concrete failure state.",
                "Look for a paired GitHub Actions workflow or provider-specific setup check that can be rerun or debugged.",
                "Only stop as blocked after there is concrete evidence that the failure cannot be advanced from the repository side.",
            ],
            "stop_only_after": "Inspecting the details URL and any paired workflow or provider-specific recovery path",
        }

    return None


def get_run_logs(run_id: int, job_id: int | None = None) -> str | None:
    """Get failed logs for a workflow run."""
    try:
        command = ["gh", "run", "view", str(run_id)]
        if job_id is not None:
            command += ["--job", str(job_id)]
        command.append("--log-failed")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout if result.stdout else result.stderr
    except subprocess.TimeoutExpired:
        return None
    except subprocess.CalledProcessError:
        return None


def main():
    parser = argparse.ArgumentParser(description="Fetch PR CI checks with failure snippets")
    parser.add_argument("--pr", type=int, help="PR number (defaults to current branch PR)")
    parser.add_argument(
        "--skip-logs",
        action="store_true",
        help="Skip failed log fetches for a faster summary-only snapshot",
    )
    args = parser.parse_args()

    # Get PR info
    pr_info = get_pr_info(args.pr)
    if not pr_info:
        print(json.dumps({"error": "No PR found for current branch"}))
        sys.exit(1)

    pr_number = pr_info["number"]
    branch = pr_info["headRefName"]
    merge_state_status = pr_info.get("mergeStateStatus", "UNKNOWN")
    review_decision = pr_info.get("reviewDecision", "")
    is_draft = pr_info.get("isDraft", False)

    # Get checks
    checks = get_checks(pr_number)
    snapshot_at = datetime.now(timezone.utc).isoformat()

    # Process checks and add failure snippets
    processed_checks = []
    failed_runs = None  # Lazy load
    workflow_run_cache: dict[str, dict[str, Any] | None] = {}
    run_log_cache: dict[tuple[int, int | None], str | None] = {}

    for check in checks:
        name = check.get("name", "unknown")
        link = check.get("link", "")
        workflow = check.get("workflow", "")
        status = check.get("bucket", check.get("state", "unknown"))
        check_type = detect_check_type(link, workflow)
        provider = detect_provider(name, workflow, link)
        check_family = detect_check_family(name, workflow, link)
        run_id, job_id = parse_actions_run_ids(link)
        processed = {
            "name": name,
            "status": status,
            "state": check.get("state", "unknown"),
            "link": link,
            "workflow": workflow,
            "event": check.get("event", ""),
            "check_type": check_type,
            "provider": provider,
            "check_family": check_family,
            "is_actionable": status not in {"pass", "skipping"},
        }
        if run_id is not None:
            processed["run_id"] = run_id
        if job_id is not None:
            processed["job_id"] = job_id

        # For failures, try to get log snippet
        if status in {"fail", "cancel"} and not args.skip_logs:
            logs: str | None = None
            resolved_run_id = run_id
            resolved_job_id = job_id

            if resolved_run_id is not None:
                cache_key = (resolved_run_id, resolved_job_id)
                if cache_key not in run_log_cache:
                    run_log_cache[cache_key] = get_run_logs(resolved_run_id, resolved_job_id)
                logs = run_log_cache[cache_key]
            else:
                if failed_runs is None:
                    failed_runs = get_failed_runs(branch)

                workflow_name = processed["workflow"] or processed["name"]
                if workflow_name not in workflow_run_cache:
                    workflow_run_cache[workflow_name] = next(
                        (r for r in failed_runs if workflow_name in r.get("name", "")),
                        None,
                    )

                matching_run = workflow_run_cache[workflow_name]
                if matching_run:
                    resolved_run_id = matching_run["databaseId"]
                    processed["run_id"] = resolved_run_id
                    cache_key = (resolved_run_id, None)
                    if cache_key not in run_log_cache:
                        run_log_cache[cache_key] = get_run_logs(resolved_run_id)
                    logs = run_log_cache[cache_key]

            if logs:
                processed["log_snippet"] = extract_failure_snippet(logs)
                processed["failure_markers"] = extract_failure_markers(logs)

        recovery_hint = build_recovery_hint(processed)
        if recovery_hint is not None:
            processed["recovery_hint"] = recovery_hint

        processed_checks.append(processed)

    # Build output
    output: dict[str, Any] = {
        "pr": {
            "number": pr_number,
            "url": pr_info.get("url", ""),
            "branch": branch,
            "base": pr_info.get("baseRefName", ""),
            "merge_state_status": merge_state_status,
            "review_decision": review_decision,
            "is_draft": is_draft,
        },
        "snapshot_at": snapshot_at,
        "logs_included": not args.skip_logs,
        "summary": {
            "total": len(processed_checks),
            "passed": sum(1 for c in processed_checks if c["status"] == "pass"),
            "failed": sum(1 for c in processed_checks if c["status"] == "fail"),
            "cancelled": sum(1 for c in processed_checks if c["status"] == "cancel"),
            "pending": sum(1 for c in processed_checks if c["status"] == "pending"),
            "skipped": sum(1 for c in processed_checks if c["status"] == "skipping"),
            "actionable": sum(
                1 for c in processed_checks if c["status"] not in {"pass", "skipping"}
            ),
        },
        "checks": processed_checks,
    }

    completion_blockers: list[str] = []
    if output["summary"]["actionable"] > 0:
        completion_blockers.append("One or more checks are still failing, pending, or cancelled")
    if is_draft:
        completion_blockers.append("Pull request is still a draft")
    if review_decision == "CHANGES_REQUESTED":
        completion_blockers.append("Review decision is CHANGES_REQUESTED")
    if merge_state_status not in {"CLEAN", "HAS_HOOKS"}:
        completion_blockers.append(f"GitHub mergeStateStatus is {merge_state_status}")

    output["completion_blockers"] = completion_blockers
    output["ready_for_merge"] = not completion_blockers

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
