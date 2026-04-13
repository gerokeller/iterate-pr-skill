#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""
Watch a PR for check-state transitions and new review activity, emitting one
stdout line per event. Designed to be driven by Claude Code's Monitor tool.

All polling uses ETag-conditional requests (`If-None-Match`), so steady-state
cycles cost a single cheap 304 per endpoint. This makes short poll intervals
(10-15s) safe on GitHub's primary rate limit.

Usage:
    uv run watch_pr_state.py [--pr NUMBER] [--repo OWNER/NAME] [--interval 15]
                             [--watch {checks,feedback,all}]
                             [--since ISO_TIMESTAMP]
                             [--exit-when {checks-settled,never}]
                             [--max-idle-cycles N]

When launched via Claude Code's Monitor tool, always pass both --pr and
--repo explicitly. The subprocess inherits the parent's cwd, which may not
be the PR branch's worktree; without --pr/--repo the watcher falls back to
`gh pr view` / `gh repo view` against cwd and will exit with
`error:no-pr-for-current-branch` if the current branch has no PR.

Event line formats (stable, parseable):
    check:<name>:<old_state>-><new_state>
    check-new:<name>:<state>
    checks-settled:passed=<N>,failed=<N>,cancelled=<N>,pending=0
    comment:<source>:<id>:<author>
    review:<state>:<author>
    heartbeat:pending=<N>
    error:<short-message>

Lines go to stdout (=> Monitor events). Diagnostics go to stderr (=> log file).

Design notes:
- Transitions only. Steady state emits nothing unless --heartbeat is given.
- Uses `gh auth token` for credentials and urllib for HTTP (no external deps).
- Transient HTTP failures are logged to stderr and retried on the next cycle.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

GITHUB_API = "https://api.github.com"
USER_AGENT = "iterate-pr-watch/1.0"
CHECK_BUCKET_FROM_CONCLUSION = {
    "success": "pass",
    "neutral": "pass",
    "skipped": "skipping",
    "failure": "fail",
    "timed_out": "fail",
    "action_required": "fail",
    "stale": "fail",
    "startup_failure": "fail",
    "cancelled": "cancel",
}
STATUS_BUCKET = {
    "success": "pass",
    "pending": "pending",
    "failure": "fail",
    "error": "fail",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def emit(line: str) -> None:
    print(line, flush=True)


def run_gh_json(args: list[str]) -> Any | None:
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=True, timeout=30
        )
        return json.loads(result.stdout) if result.stdout.strip() else None
    except subprocess.CalledProcessError as e:
        log(f"gh {' '.join(args)} failed: {e.stderr.strip()}")
        return None
    except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        log(f"gh {' '.join(args)} parse/timeout: {e}")
        return None


def gh_token() -> str | None:
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=10
        )
        return out.stdout.strip() or None
    except subprocess.CalledProcessError as e:
        log(f"gh auth token failed: {e.stderr.strip()}")
        return None


class ConditionalClient:
    """Minimal GitHub REST client with per-URL ETag caching."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._etags: dict[str, str] = {}

    def get(self, path: str, query: dict[str, str] | None = None) -> tuple[int, Any | None]:
        url = GITHUB_API + path
        if query:
            from urllib.parse import urlencode

            url = f"{url}?{urlencode(query)}"
        req = urlrequest.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", USER_AGENT)
        if url in self._etags:
            req.add_header("If-None-Match", self._etags[url])
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                etag = resp.headers.get("ETag")
                if etag:
                    self._etags[url] = etag
                body = resp.read()
                if not body:
                    return resp.status, None
                return resp.status, json.loads(body.decode("utf-8"))
        except urlerror.HTTPError as e:
            if e.code == 304:
                return 304, None
            log(f"HTTP {e.code} for {url}: {e.reason}")
            return e.code, None
        except (urlerror.URLError, TimeoutError, json.JSONDecodeError) as e:
            log(f"HTTP error for {url}: {e}")
            return 0, None


def get_pr_info(explicit: int | None, repo: str | None = None) -> dict[str, Any] | None:
    args = ["pr", "view", "--json", "number,headRefOid,baseRepository"]
    if explicit:
        args.insert(2, str(explicit))
    if repo:
        args.extend(["--repo", repo])
    result = run_gh_json(args)
    return result if isinstance(result, dict) else None


def get_repo_slug() -> str | None:
    info = run_gh_json(["repo", "view", "--json", "nameWithOwner"])
    return info.get("nameWithOwner") if isinstance(info, dict) else None


def bucket_check_run(cr: dict[str, Any]) -> str:
    status = cr.get("status")
    if status != "completed":
        return "pending"
    return CHECK_BUCKET_FROM_CONCLUSION.get(cr.get("conclusion") or "", "fail")


def fetch_check_state(
    client: ConditionalClient,
    owner: str,
    repo: str,
    sha: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """Fetch check-runs + combined status and merge into {name: bucket}.

    Uses 304 caching per endpoint. When both endpoints return 304 we return
    the last-known merged state (callers compare to previous and will emit
    nothing if unchanged).
    """
    changed = False
    # check-runs
    status, body = client.get(
        f"/repos/{owner}/{repo}/commits/{sha}/check-runs", {"per_page": "100"}
    )
    if status == 200 and isinstance(body, dict):
        runs = {cr["name"]: bucket_check_run(cr) for cr in body.get("check_runs", [])}
        cache["check_runs"] = runs
        changed = True
    elif status not in (200, 304):
        return None
    # combined status (for external status contexts like Vercel/Supabase)
    status, body = client.get(f"/repos/{owner}/{repo}/commits/{sha}/status", {"per_page": "100"})
    if status == 200 and isinstance(body, dict):
        statuses = {
            s["context"]: STATUS_BUCKET.get(s.get("state") or "", "pending")
            for s in body.get("statuses", [])
        }
        cache["statuses"] = statuses
        changed = True
    elif status not in (200, 304):
        return None
    if not cache:
        return None
    # merge (status contexts keyed by name; check-runs take precedence on collision)
    merged: dict[str, str] = {}
    merged.update(cache.get("statuses", {}))
    merged.update(cache.get("check_runs", {}))
    # Always return merged so transitions can be compared; 304-only cycles
    # return the unchanged prior state, which the caller diffs to nothing.
    _ = changed
    return merged


def fetch_comments_since(
    client: ConditionalClient, owner: str, repo: str, pr: int, since: str
) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    status, body = client.get(
        f"/repos/{owner}/{repo}/issues/{pr}/comments",
        {"since": since, "per_page": "100"},
    )
    if status == 200 and isinstance(body, list):
        out.extend(("issue", c) for c in body)
    status, body = client.get(
        f"/repos/{owner}/{repo}/pulls/{pr}/comments",
        {"since": since, "per_page": "100"},
    )
    if status == 200 and isinstance(body, list):
        out.extend(("review", c) for c in body)
    return out


def fetch_reviews_since(
    client: ConditionalClient, owner: str, repo: str, pr: int, baseline: datetime
) -> list[dict[str, Any]]:
    status, body = client.get(f"/repos/{owner}/{repo}/pulls/{pr}/reviews", {"per_page": "100"})
    if status != 200 or not isinstance(body, list):
        return []
    newer: list[dict[str, Any]] = []
    for r in body:
        submitted = r.get("submitted_at")
        if not submitted:
            continue
        try:
            t = datetime.fromisoformat(submitted.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t > baseline:
            newer.append(r)
    return newer


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pr", type=int)
    p.add_argument(
        "--repo",
        type=str,
        help=(
            "owner/name slug. Required when cwd isn't the PR's worktree "
            "(e.g. when launched via the Monitor tool from a different path)."
        ),
    )
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--watch", choices=["checks", "feedback", "all"], default="all")
    p.add_argument("--since", type=str, help="ISO-8601 baseline for new comments/reviews")
    p.add_argument("--exit-when", choices=["checks-settled", "never"], default="never")
    p.add_argument(
        "--max-idle-cycles",
        type=int,
        default=0,
        help="After checks settle, wait this many idle cycles before exiting (0 = immediate).",
    )
    p.add_argument("--heartbeat", action="store_true")
    args = p.parse_args()

    token = gh_token()
    if not token:
        emit("error:no-github-token")
        return 2
    client = ConditionalClient(token)

    # Resolve repo slug first so PR lookup can be cwd-independent when --repo
    # is supplied. Falls back to `gh repo view` against cwd otherwise.
    if args.repo:
        if "/" not in args.repo:
            emit("error:invalid-repo-slug-expected-owner/name")
            return 2
        slug = args.repo
    else:
        resolved = get_repo_slug()
        if not resolved or "/" not in resolved:
            emit("error:cannot-resolve-repo-slug-pass-repo-owner/name")
            return 2
        slug = resolved
    owner, repo = slug.split("/", 1)

    pr_info = get_pr_info(args.pr, repo=slug)
    if not pr_info or "number" not in pr_info:
        if args.pr:
            emit(f"error:pr-{args.pr}-not-found-in-{slug}")
        else:
            emit("error:no-pr-for-current-branch-pass-pr-number")
        return 2
    pr_number = pr_info["number"]
    head_sha = pr_info.get("headRefOid")

    baseline_iso = args.since or datetime.now(timezone.utc).isoformat()
    baseline_dt = parse_iso(baseline_iso)
    seen_comment_ids: set[int] = set()
    seen_review_ids: set[int] = set()
    last_checks: dict[str, str] | None = None
    check_cache: dict[str, dict[str, str]] = {}
    idle_cycles_after_settle = 0

    log(
        f"watch_pr_state: pr={pr_number} repo={slug} sha={head_sha} "
        f"watch={args.watch} since={baseline_iso} interval={args.interval}s"
    )

    while True:
        # --- checks ---
        if args.watch in ("checks", "all") and head_sha:
            current = fetch_check_state(client, owner, repo, head_sha, check_cache)
            if current is not None:
                if last_checks is None:
                    last_checks = current
                else:
                    for name, state in current.items():
                        prev = last_checks.get(name)
                        if prev is None:
                            emit(f"check-new:{name}:{state}")
                        elif prev != state:
                            emit(f"check:{name}:{prev}->{state}")
                    last_checks = current

                pending = sum(1 for s in current.values() if s == "pending")
                settled = pending == 0 and len(current) > 0
                if args.heartbeat:
                    emit(f"heartbeat:pending={pending}")
                if settled:
                    passed = sum(1 for s in current.values() if s == "pass")
                    failed = sum(1 for s in current.values() if s == "fail")
                    cancelled = sum(1 for s in current.values() if s == "cancel")
                    emit(
                        f"checks-settled:passed={passed},failed={failed},"
                        f"cancelled={cancelled},pending=0"
                    )
                    if args.exit_when == "checks-settled":
                        idle_cycles_after_settle += 1
                        if idle_cycles_after_settle > args.max_idle_cycles:
                            return 0

        # --- feedback ---
        if args.watch in ("feedback", "all"):
            for source, c in fetch_comments_since(client, owner, repo, pr_number, baseline_iso):
                cid = c.get("id")
                if cid is None or cid in seen_comment_ids:
                    continue
                seen_comment_ids.add(cid)
                author = (c.get("user") or {}).get("login", "unknown")
                emit(f"comment:{source}:{cid}:{author}")
            for r in fetch_reviews_since(client, owner, repo, pr_number, baseline_dt):
                rid = r.get("id")
                if rid is None or rid in seen_review_ids:
                    continue
                seen_review_ids.add(rid)
                author = (r.get("user") or {}).get("login", "unknown")
                state = r.get("state", "unknown")
                emit(f"review:{state}:{author}")

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
