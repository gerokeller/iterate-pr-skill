from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_DIR = os.path.join(_REPO_ROOT, "skills", "iterate-pr")
for _entry in (_SKILL_DIR, os.path.join(_SKILL_DIR, "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import fetch_pr_feedback as fpf  # noqa: E402


class IsBotTests(unittest.TestCase):
    def test_generic_bot_suffix(self) -> None:
        self.assertTrue(fpf.is_bot("someservice-bot"))
        self.assertTrue(fpf.is_bot("whatever[bot]"))

    def test_known_generic_bots(self) -> None:
        self.assertTrue(fpf.is_bot("dependabot"))
        self.assertTrue(fpf.is_bot("renovate"))
        self.assertTrue(fpf.is_bot("github-actions"))
        self.assertTrue(fpf.is_bot("copilot"))

    def test_provider_contributed_bots(self) -> None:
        self.assertTrue(fpf.is_bot("codecov[bot]"))
        self.assertTrue(fpf.is_bot("sentry-io"))
        self.assertTrue(fpf.is_bot("seer"))
        self.assertTrue(fpf.is_bot("cursor"))
        self.assertTrue(fpf.is_bot("bugbot"))
        self.assertTrue(fpf.is_bot("coderabbitai"))

    def test_humans_not_matched(self) -> None:
        self.assertFalse(fpf.is_bot("gerokeller"))
        self.assertFalse(fpf.is_bot("alice-dev"))
        self.assertFalse(fpf.is_bot("carol"))


class DetectLogafTests(unittest.TestCase):
    def test_high_markers(self) -> None:
        self.assertEqual(fpf.detect_logaf("h: this is broken"), "high")
        self.assertEqual(fpf.detect_logaf("[H] critical"), "high")
        self.assertEqual(fpf.detect_logaf("High: fix this"), "high")

    def test_medium_markers(self) -> None:
        self.assertEqual(fpf.detect_logaf("m: consider renaming"), "medium")
        self.assertEqual(fpf.detect_logaf("[m] review"), "medium")
        self.assertEqual(fpf.detect_logaf("Medium: improve"), "medium")

    def test_low_markers(self) -> None:
        self.assertEqual(fpf.detect_logaf("l: nit"), "low")
        self.assertEqual(fpf.detect_logaf("[L] optional"), "low")
        self.assertEqual(fpf.detect_logaf("Low: style"), "low")

    def test_no_marker(self) -> None:
        self.assertIsNone(fpf.detect_logaf("just a regular comment"))

    def test_leading_whitespace_ok(self) -> None:
        self.assertEqual(fpf.detect_logaf("   h: indented"), "high")


class CategorizeCommentTests(unittest.TestCase):
    def test_bot_author_classified_as_bot(self) -> None:
        comment = {"author": {"login": "codecov[bot]"}}
        self.assertEqual(fpf.categorize_comment(comment, "coverage dropped"), "bot")

    def test_bot_author_via_user_field(self) -> None:
        comment = {"user": {"login": "dependabot"}}
        self.assertEqual(fpf.categorize_comment(comment, "bump x"), "bot")

    def test_logaf_marker_takes_precedence_over_content_heuristics(self) -> None:
        # "must fix" is a high-heuristic, but the low-marker should win
        comment = {"author": {"login": "alice"}}
        self.assertEqual(
            fpf.categorize_comment(comment, "l: you must fix this"),
            "low",
        )

    def test_high_priority_content_heuristics(self) -> None:
        comment = {"author": {"login": "alice"}}
        self.assertEqual(
            fpf.categorize_comment(comment, "This is broken"),
            "high",
        )
        self.assertEqual(
            fpf.categorize_comment(comment, "must fix before merge"),
            "high",
        )
        self.assertEqual(
            fpf.categorize_comment(comment, "security vulnerability here"),
            "high",
        )

    def test_low_priority_content_heuristics(self) -> None:
        comment = {"author": {"login": "alice"}}
        self.assertEqual(
            fpf.categorize_comment(comment, "nit: trailing whitespace"),
            "low",
        )
        self.assertEqual(
            fpf.categorize_comment(comment, "suggestion: rename"),
            "low",
        )
        self.assertEqual(
            fpf.categorize_comment(comment, "consider using a constant"),
            "low",
        )

    def test_default_medium(self) -> None:
        comment = {"author": {"login": "alice"}}
        self.assertEqual(
            fpf.categorize_comment(comment, "please update the test"),
            "medium",
        )


class ExtractFeedbackItemTests(unittest.TestCase):
    def test_minimal_fields(self) -> None:
        item = fpf.extract_feedback_item(body="x", author="alice")
        self.assertEqual(item["author"], "alice")
        self.assertEqual(item["body"], "x")
        self.assertEqual(item["full_body"], "x")
        self.assertNotIn("path", item)
        self.assertNotIn("resolved", item)

    def test_summary_truncates_long_body(self) -> None:
        body = "a" * 500
        item = fpf.extract_feedback_item(body=body, author="alice")
        self.assertTrue(item["body"].endswith("..."))
        self.assertLessEqual(len(item["body"]), 204)
        self.assertEqual(item["full_body"], body)

    def test_summary_collapses_newlines(self) -> None:
        item = fpf.extract_feedback_item(body="line1\nline2", author="alice")
        self.assertNotIn("\n", item["body"])

    def test_optional_fields_included_when_provided(self) -> None:
        item = fpf.extract_feedback_item(
            body="x",
            author="alice",
            path="src/foo.ts",
            line=42,
            url="https://github.com/...",
            thread_id="T1",
            comment_id=123,
            source="review_thread",
            created_at="2026-01-01T00:00:00Z",
            is_resolved=True,
            is_outdated=True,
        )
        self.assertEqual(item["path"], "src/foo.ts")
        self.assertEqual(item["line"], 42)
        self.assertEqual(item["thread_id"], "T1")
        self.assertEqual(item["comment_id"], 123)
        self.assertEqual(item["source"], "review_thread")
        self.assertTrue(item["resolved"])
        self.assertTrue(item["outdated"])

    def test_resolved_and_outdated_omitted_when_false(self) -> None:
        item = fpf.extract_feedback_item(
            body="x", author="alice", is_resolved=False, is_outdated=False
        )
        self.assertNotIn("resolved", item)
        self.assertNotIn("outdated", item)


if __name__ == "__main__":
    unittest.main()
