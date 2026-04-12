#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""
Fetch and categorize PR review feedback.

Usage:
    python fetch_pr_feedback.py [--pr PR_NUMBER]

If --pr is not specified, uses the PR for the current branch.

Output: JSON to stdout with categorized feedback.

Categories (using LOGAF scale - see https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale):
- high: Must address before merge (h:, blocker, changes requested)
- medium: Should address (m:, standard feedback)
- low: Optional suggestions (l:, nit, style)
- bot: Automated comments (Codecov, Sentry bot, etc.)
- resolved: Already resolved threads
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
from typing import Any


# Known bot usernames and patterns
BOT_PATTERNS = [
    r"(?i)bot$",
    r"(?i)^codecov",
    r"(?i)^sentry",
    r"(?i)^dependabot",
    r"(?i)^renovate",
    r"(?i)^github-actions",
    r"(?i)^mergify",
    r"(?i)^semantic-release",
    r"(?i)^sonarcloud",
    r"(?i)^snyk",
    r"(?i)^cursor",
    r"(?i)^bugbot",
    r"(?i)^seer",
    r"(?i)^copilot",
    r"(?i)\[bot\]$",
]


def run_gh(args: list[str]) -> dict[str, Any] | list[Any] | None:
    """Run a gh CLI command and return parsed JSON output."""
    try:
        result = subprocess.run(
            ["gh"] + args,
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


def get_repo_info() -> tuple[str, str] | None:
    """Get owner and repo name from local git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    remote = result.stdout.strip()
    if not remote:
        return None

    ssh_match = re.match(r"git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", remote)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    https_match = re.match(r"https://[^/]+/([^/]+)/(.+?)(?:\.git)?$", remote)
    if https_match:
        return https_match.group(1), https_match.group(2)

    return None


def get_pr_info(pr_number: int | None = None) -> dict[str, Any] | None:
    """Get PR info, optionally by number or for current branch."""
    args = ["pr", "view", "--json", "number,url,headRefName,author,reviews,reviewDecision"]
    if pr_number:
        args.insert(2, str(pr_number))
    return run_gh(args)


def is_bot(username: str) -> bool:
    """Check if username matches known bot patterns."""
    for pattern in BOT_PATTERNS:
        if re.search(pattern, username):
            return True
    return False


def get_issue_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Get PR conversation comments (includes bot comments)."""
    result = run_gh([
        "api",
        f"repos/{owner}/{repo}/issues/{pr_number}/comments",
        "--paginate",
    ])
    return result if isinstance(result, list) else []


def get_comment_url(comment: dict[str, Any]) -> str | None:
    """Get the canonical URL for a comment."""
    return comment.get("html_url") or comment.get("url")


def get_review_threads(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Get review threads with resolution status via GraphQL."""
    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              isOutdated
              path
              line
              comments(first: 10) {
                nodes {
                  id
                  url
                  body
                  author {
                    login
                  }
                  createdAt
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        result = subprocess.run(
            [
                "gh", "api", "graphql",
                "-f", f"query={query}",
                "-F", f"owner={owner}",
                "-F", f"repo={repo}",
                "-F", f"pr={pr_number}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        threads = data.get("data", {}).get("repository", {}).get("pullRequest", {}).get("reviewThreads", {}).get("nodes", [])
        return threads
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []


def detect_logaf(body: str) -> str | None:
    """Detect LOGAF scale markers in comment body.

    LOGAF scale (https://develop.sentry.dev/engineering-practices/code-review/#logaf-scale):
    - l: / [l] / low: → low priority (optional)
    - m: / [m] / medium: → medium priority (should address)
    - h: / [h] / high: → high priority (must address)

    Returns 'high', 'medium', 'low', or None if no marker found.
    """
    # Check for LOGAF markers at start of comment (with optional whitespace)
    logaf_patterns = [
        # h: or [h] or high: patterns
        (r"^\s*(?:h:|h\s*:|high:|\[h\])", "high"),
        # m: or [m] or medium: patterns
        (r"^\s*(?:m:|m\s*:|medium:|\[m\])", "medium"),
        # l: or [l] or low: patterns
        (r"^\s*(?:l:|l\s*:|low:|\[l\])", "low"),
    ]

    for pattern, level in logaf_patterns:
        if re.search(pattern, body, re.IGNORECASE):
            return level

    return None


def categorize_comment(comment: dict[str, Any], body: str) -> str:
    """Categorize a comment based on content and author.

    Uses LOGAF scale: high (must fix), medium (should fix), low (optional).
    """
    author = comment.get("author", {}).get("login", "") or comment.get("user", {}).get("login", "")

    if is_bot(author):
        return "bot"

    # Check for explicit LOGAF markers first
    logaf_level = detect_logaf(body)
    if logaf_level:
        return logaf_level

    # Look for high-priority (blocking) indicators
    high_patterns = [
        r"(?i)must\s+(fix|change|update|address)",
        r"(?i)this\s+(is\s+)?(wrong|incorrect|broken|buggy)",
        r"(?i)security\s+(issue|vulnerability|concern)",
        r"(?i)will\s+(break|cause|fail)",
        r"(?i)critical",
        r"(?i)blocker",
    ]

    for pattern in high_patterns:
        if re.search(pattern, body):
            return "high"

    # Look for low-priority (suggestion) indicators
    low_patterns = [
        r"(?i)nit[:\s]",
        r"(?i)nitpick",
        r"(?i)suggestion[:\s]",
        r"(?i)consider\s+",
        r"(?i)could\s+(also\s+)?",
        r"(?i)might\s+(want\s+to|be\s+better)",
        r"(?i)optional[:\s]",
        r"(?i)minor[:\s]",
        r"(?i)style[:\s]",
        r"(?i)prefer\s+",
        r"(?i)what\s+do\s+you\s+think",
        r"(?i)up\s+to\s+you",
        r"(?i)take\s+it\s+or\s+leave",
        r"(?i)fwiw",
    ]

    for pattern in low_patterns:
        if re.search(pattern, body):
            return "low"

    # Default to medium for non-bot comments without clear indicators
    return "medium"


def extract_feedback_item(
    body: str,
    author: str,
    path: str | None = None,
    line: int | None = None,
    url: str | None = None,
    thread_id: str | None = None,
    comment_id: str | int | None = None,
    source: str | None = None,
    created_at: str | None = None,
    is_resolved: bool = False,
    is_outdated: bool = False,
) -> dict[str, Any]:
    """Create a standardized feedback item."""
    # Truncate long bodies for summary
    summary = body[:200] + "..." if len(body) > 200 else body
    summary = summary.replace("\n", " ").strip()

    item = {
        "author": author,
        "body": summary,
        "full_body": body,
    }

    if path:
        item["path"] = path
    if line:
        item["line"] = line
    if url:
        item["url"] = url
    if thread_id:
        item["thread_id"] = thread_id
    if comment_id is not None:
        item["comment_id"] = comment_id
    if source:
        item["source"] = source
    if created_at:
        item["created_at"] = created_at
    if is_resolved:
        item["resolved"] = True
    if is_outdated:
        item["outdated"] = True

    return item


def main():
    parser = argparse.ArgumentParser(description="Fetch and categorize PR feedback")
    parser.add_argument("--pr", type=int, help="PR number (defaults to current branch PR)")
    parser.add_argument(
        "--skip-issue-comments",
        action="store_true",
        help="Skip top-level PR conversation comments for a faster partial snapshot",
    )
    args = parser.parse_args()

    # Get repo info
    repo_info = get_repo_info()
    if not repo_info:
        print(json.dumps({"error": "Could not determine repository"}))
        sys.exit(1)
    owner, repo = repo_info

    # Get PR info
    pr_info = get_pr_info(args.pr)
    if not pr_info:
        print(json.dumps({"error": "No PR found for current branch"}))
        sys.exit(1)

    pr_number = pr_info["number"]
    pr_author = pr_info.get("author", {}).get("login", "")
    snapshot_at = datetime.now(timezone.utc).isoformat()

    # Get review decision
    review_decision = pr_info.get("reviewDecision", "")

    # Categorized feedback using LOGAF scale
    feedback = {
        "high": [],      # Must address before merge
        "medium": [],    # Should address
        "low": [],       # Optional suggestions
        "bot": [],
        "resolved": [],
    }

    # Process reviews for overall status
    reviews = pr_info.get("reviews", [])
    for review in reviews:
        if review.get("state") == "CHANGES_REQUESTED":
            author = review.get("author", {}).get("login", "")
            body = review.get("body", "")
            if body and author != pr_author:
                item = extract_feedback_item(body, author)
                item["source"] = "review"
                item["type"] = "changes_requested"
                feedback["high"].append(item)

    # Track review-thread resolution explicitly because unresolved conversations
    # can block merge even when the comment content is otherwise low-signal.
    total_review_threads = 0
    unresolved_review_threads = 0

    # Get review threads (inline comments with resolution status)
    threads = get_review_threads(owner, repo, pr_number)
    for thread in threads:
        if not thread.get("comments", {}).get("nodes"):
            continue

        first_comment = thread["comments"]["nodes"][0]
        author = first_comment.get("author", {}).get("login", "")
        body = first_comment.get("body", "")

        # Skip if author is PR author (self-comments)
        if author == pr_author:
            continue

        # Skip empty or very short comments
        if not body or len(body.strip()) < 3:
            continue

        total_review_threads += 1
        is_resolved = thread.get("isResolved", False)
        is_outdated = thread.get("isOutdated", False)
        if not is_resolved:
            unresolved_review_threads += 1

        item = extract_feedback_item(
            body=body,
            author=author,
            path=thread.get("path"),
            line=thread.get("line"),
            url=first_comment.get("url"),
            thread_id=thread.get("id"),
            comment_id=first_comment.get("id"),
            source="review_thread",
            created_at=first_comment.get("createdAt"),
            is_resolved=is_resolved,
            is_outdated=is_outdated,
        )
        item["thread_comment_count"] = len(thread["comments"]["nodes"])
        item["latest_activity_at"] = max(
            (
                comment.get("createdAt")
                for comment in thread["comments"]["nodes"]
                if comment.get("createdAt")
            ),
            default=None,
        )

        if is_resolved:
            feedback["resolved"].append(item)
        elif is_bot(author):
            feedback["bot"].append(item)
        else:
            category = categorize_comment(first_comment, body)
            feedback[category].append(item)

    if not args.skip_issue_comments:
        # Get issue comments (general PR conversation)
        issue_comments = get_issue_comments(owner, repo, pr_number)

        for comment in issue_comments:
            author = comment.get("user", {}).get("login", "")
            body = comment.get("body", "")

            # Skip if author is PR author
            if author == pr_author:
                continue

            # Skip empty comments
            if not body or len(body.strip()) < 3:
                continue

            item = extract_feedback_item(
                body=body,
                author=author,
                url=get_comment_url(comment),
                comment_id=comment.get("id"),
                source="issue_comment",
                created_at=comment.get("created_at"),
            )

            if is_bot(author):
                feedback["bot"].append(item)
            else:
                category = categorize_comment(comment, body)
                feedback[category].append(item)

    # Build output
    output = {
        "pr": {
            "number": pr_number,
            "url": pr_info.get("url", ""),
            "author": pr_author,
            "review_decision": review_decision,
        },
        "snapshot_at": snapshot_at,
        "issue_comments_included": not args.skip_issue_comments,
        "full_coverage": not args.skip_issue_comments,
        "summary": {
            "high": len(feedback["high"]),
            "medium": len(feedback["medium"]),
            "low": len(feedback["low"]),
            "bot_comments": len(feedback["bot"]),
            "resolved": len(feedback["resolved"]),
            "total_review_threads": total_review_threads,
            "resolved_review_threads": total_review_threads - unresolved_review_threads,
            "unresolved_review_threads": unresolved_review_threads,
            "all_review_threads_resolved": unresolved_review_threads == 0,
            "needs_attention": len(feedback["high"]) + len(feedback["medium"]),
            "actionable_items": len(feedback["high"]) + len(feedback["medium"]) + len(feedback["low"]),
        },
        "feedback": feedback,
    }

    # Add actionable summary based on LOGAF priorities
    if feedback["high"]:
        output["action_required"] = "Address high-priority feedback before merge"
    elif feedback["medium"]:
        output["action_required"] = "Address medium-priority feedback"
    elif feedback["low"]:
        output["action_required"] = "Review low-priority suggestions and decide fix or reject"
    else:
        output["action_required"] = None

    if args.skip_issue_comments:
        output["completion_requires_full_fetch"] = True
        output["notes"] = [
            "Top-level PR conversation comments were skipped for speed.",
            "Run without --skip-issue-comments before replying, resolving, or declaring the PR clean.",
        ]
    else:
        output["completion_requires_full_fetch"] = False

    feedback_blockers = []
    if unresolved_review_threads > 0:
        feedback_blockers.append("Unresolved review threads remain")
    if output["summary"]["actionable_items"] > 0:
        feedback_blockers.append("Actionable review feedback remains")
    if output["action_required"]:
        feedback_blockers.append(output["action_required"])
    if review_decision == "CHANGES_REQUESTED":
        feedback_blockers.append("Review decision is CHANGES_REQUESTED")
    if args.skip_issue_comments:
        feedback_blockers.append("Feedback snapshot is partial; full fetch required before completion")

    output["completion_blockers"] = feedback_blockers
    output["feedback_cleared"] = not feedback_blockers

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
