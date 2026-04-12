from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _entry in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import fetch_pr_checks as fpc  # noqa: E402


class ParseActionsRunIdsTests(unittest.TestCase):
    def test_parses_run_and_job(self) -> None:
        run_id, job_id = fpc.parse_actions_run_ids(
            "https://github.com/foo/bar/actions/runs/123456/job/7891011"
        )
        self.assertEqual(run_id, 123456)
        self.assertEqual(job_id, 7891011)

    def test_parses_run_only(self) -> None:
        run_id, job_id = fpc.parse_actions_run_ids("https://github.com/foo/bar/actions/runs/42")
        self.assertEqual(run_id, 42)
        self.assertIsNone(job_id)

    def test_returns_none_for_unrelated_link(self) -> None:
        run_id, job_id = fpc.parse_actions_run_ids("https://vercel.com/x/y/abcdef")
        self.assertIsNone(run_id)
        self.assertIsNone(job_id)


class DetectCheckTypeTests(unittest.TestCase):
    def test_github_actions_from_link(self) -> None:
        self.assertEqual(
            fpc.detect_check_type("https://github.com/o/r/actions/runs/1", ""),
            "github-actions",
        )

    def test_github_actions_from_workflow(self) -> None:
        self.assertEqual(fpc.detect_check_type("", "CI"), "github-actions")

    def test_status_context_when_no_workflow_or_link(self) -> None:
        self.assertEqual(fpc.detect_check_type("", ""), "status-context")

    def test_status_context_for_external_link(self) -> None:
        self.assertEqual(
            fpc.detect_check_type("https://vercel.com/preview/x", ""),
            "status-context",
        )


class DetectProviderTests(unittest.TestCase):
    def test_registry_match_returns_provider_name(self) -> None:
        self.assertEqual(
            fpc.detect_provider("Configure Supabase Preview", "", ""),
            "supabase",
        )
        self.assertEqual(fpc.detect_provider("codecov/patch", "", ""), "codecov")

    def test_falls_back_to_github_actions_for_unclaimed_actions_check(self) -> None:
        self.assertEqual(
            fpc.detect_provider("lint", "CI", "https://github.com/o/r/actions/runs/1"),
            "github-actions",
        )

    def test_falls_back_to_external_for_unclaimed_status_context(self) -> None:
        self.assertEqual(
            fpc.detect_provider("someexternal", "", "https://other.example/status/1"),
            "external",
        )


class DetectCheckFamilyTests(unittest.TestCase):
    def test_supabase_preview(self) -> None:
        self.assertEqual(
            fpc.detect_check_family("Configure Supabase Preview", "", ""),
            "supabase-preview",
        )

    def test_codecov_coverage(self) -> None:
        self.assertEqual(
            fpc.detect_check_family("codecov/patch", "", ""),
            "codecov-coverage",
        )

    def test_returns_none_when_no_provider_matches(self) -> None:
        self.assertIsNone(fpc.detect_check_family("lint", "CI", ""))


class ExtractFailureSnippetTests(unittest.TestCase):
    def test_returns_context_around_first_failure(self) -> None:
        lines = [f"line {i}" for i in range(20)]
        lines[10] = "Error: something exploded"
        text = "\n".join(lines)
        snippet = fpc.extract_failure_snippet(text, max_lines=10)
        self.assertIn("Error: something exploded", snippet)
        # Expect 5 lines before first failure to be included
        self.assertIn("line 5", snippet)

    def test_falls_back_to_last_n_lines_when_no_failure(self) -> None:
        lines = [f"ok {i}" for i in range(100)]
        snippet = fpc.extract_failure_snippet("\n".join(lines), max_lines=10)
        self.assertIn("ok 99", snippet)
        self.assertNotIn("ok 0", snippet)

    def test_counts_remaining_failures_after_snippet(self) -> None:
        lines = ["pre"] + ["Error:" + str(i) for i in range(60)]
        snippet = fpc.extract_failure_snippet("\n".join(lines), max_lines=10)
        self.assertIn("more error", snippet.lower())


class ExtractFailureMarkersTests(unittest.TestCase):
    def test_extracts_supabase_markers(self) -> None:
        log = "some output\n::error MIGRATIONS_FAILED\nTimeout waiting for branch\n"
        markers = fpc.extract_failure_markers(log)
        self.assertIn("MIGRATIONS_FAILED", markers)
        self.assertIn("TIMEOUT_WAITING_FOR_BRANCH", markers)

    def test_empty_when_no_markers(self) -> None:
        self.assertEqual(fpc.extract_failure_markers("all good"), [])


class BuildRecoveryHintTests(unittest.TestCase):
    def test_supabase_preview_failure_gets_provider_hint(self) -> None:
        check = {
            "status": "fail",
            "provider": "supabase",
            "check_family": "supabase-preview",
            "check_type": "github-actions",
            "failure_markers": ["MIGRATIONS_FAILED"],
        }
        hint = fpc.build_recovery_hint(check)
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint["classification"], "supabase-preview")
        self.assertIn("MIGRATIONS_FAILED", hint["summary"])

    def test_codecov_failure_gets_provider_hint(self) -> None:
        check = {
            "status": "fail",
            "provider": "codecov",
            "check_family": "codecov-coverage",
            "check_type": "status-context",
            "failure_markers": [],
        }
        hint = fpc.build_recovery_hint(check)
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint["classification"], "codecov-coverage")

    def test_external_status_fallback_applies_when_no_provider_hint(self) -> None:
        check = {
            "status": "fail",
            "provider": "vercel",
            "check_family": "vercel-preview",
            "check_type": "status-context",
            "failure_markers": [],
        }
        hint = fpc.build_recovery_hint(check)
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint["classification"], "external-status")

    def test_passing_github_actions_check_has_no_hint(self) -> None:
        check: dict[str, object] = {
            "status": "pass",
            "provider": "github-actions",
            "check_family": None,
            "check_type": "github-actions",
            "failure_markers": [],
        }
        self.assertIsNone(fpc.build_recovery_hint(check))

    def test_failing_github_actions_check_without_provider_has_no_hint(self) -> None:
        # github-actions is not a registered Provider; the external-status
        # fallback does not apply to github-actions check_type.
        check: dict[str, object] = {
            "status": "fail",
            "provider": "github-actions",
            "check_family": None,
            "check_type": "github-actions",
            "failure_markers": [],
        }
        self.assertIsNone(fpc.build_recovery_hint(check))


if __name__ == "__main__":
    unittest.main()
