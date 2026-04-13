from __future__ import annotations

import io
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from urllib import error as urlerror

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _entry in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import watch_pr_state as wps  # noqa: E402


class BucketCheckRunTests(unittest.TestCase):
    def test_in_progress_is_pending(self) -> None:
        self.assertEqual(wps.bucket_check_run({"status": "in_progress"}), "pending")

    def test_queued_is_pending(self) -> None:
        self.assertEqual(wps.bucket_check_run({"status": "queued"}), "pending")

    def test_success_conclusion(self) -> None:
        self.assertEqual(
            wps.bucket_check_run({"status": "completed", "conclusion": "success"}),
            "pass",
        )

    def test_neutral_is_pass(self) -> None:
        self.assertEqual(
            wps.bucket_check_run({"status": "completed", "conclusion": "neutral"}),
            "pass",
        )

    def test_skipped_is_skipping(self) -> None:
        self.assertEqual(
            wps.bucket_check_run({"status": "completed", "conclusion": "skipped"}),
            "skipping",
        )

    def test_cancelled_bucket(self) -> None:
        self.assertEqual(
            wps.bucket_check_run({"status": "completed", "conclusion": "cancelled"}),
            "cancel",
        )

    def test_failure_variants(self) -> None:
        for conclusion in ("failure", "timed_out", "action_required", "stale"):
            self.assertEqual(
                wps.bucket_check_run({"status": "completed", "conclusion": conclusion}),
                "fail",
                msg=conclusion,
            )

    def test_unknown_conclusion_defaults_to_fail(self) -> None:
        self.assertEqual(
            wps.bucket_check_run({"status": "completed", "conclusion": "weird"}),
            "fail",
        )


class ParseIsoTests(unittest.TestCase):
    def test_z_suffix(self) -> None:
        dt = wps.parse_iso("2026-04-12T10:00:00Z")
        self.assertEqual(dt, datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc))

    def test_offset_suffix(self) -> None:
        dt = wps.parse_iso("2026-04-12T10:00:00+00:00")
        self.assertEqual(dt, datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc))


class _FakeResponse:
    """Context-manager-compatible stand-in for urllib's response."""

    def __init__(
        self,
        body: dict | list | None = None,
        status: int = 200,
        etag: str | None = None,
    ) -> None:
        self.status = status
        self._body = b"" if body is None else json.dumps(body).encode("utf-8")
        self._etag = etag

    class _Headers:
        def __init__(self, etag: str | None) -> None:
            self._etag = etag

        def get(self, key: str) -> str | None:
            if key.lower() == "etag":
                return self._etag
            return None

    @property
    def headers(self) -> _FakeResponse._Headers:
        return _FakeResponse._Headers(self._etag)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _http_error_304(url: str) -> urlerror.HTTPError:
    from email.message import Message

    return urlerror.HTTPError(url, 304, "Not Modified", Message(), io.BytesIO(b""))


class ConditionalClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = wps.ConditionalClient(token="fake-token")

    @patch.object(wps.urlrequest, "urlopen")
    def test_first_get_sends_no_if_none_match_and_caches_etag(self, urlopen: MagicMock) -> None:
        urlopen.return_value = _FakeResponse(body={"ok": True}, etag='"v1"')
        status, body = self.client.get("/x")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})
        req = urlopen.call_args.args[0]
        self.assertIsNone(req.get_header("If-none-match"))
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-token")
        self.assertIn("github", req.full_url)

    @patch.object(wps.urlrequest, "urlopen")
    def test_second_get_sends_cached_etag(self, urlopen: MagicMock) -> None:
        urlopen.side_effect = [
            _FakeResponse(body={"v": 1}, etag='"v1"'),
            _FakeResponse(body={"v": 2}, etag='"v2"'),
        ]
        self.client.get("/x")
        self.client.get("/x")
        second_req = urlopen.call_args_list[1].args[0]
        self.assertEqual(second_req.get_header("If-none-match"), '"v1"')

    @patch.object(wps.urlrequest, "urlopen")
    def test_304_returns_none_body_and_keeps_cached_etag(self, urlopen: MagicMock) -> None:
        urlopen.side_effect = [
            _FakeResponse(body={"v": 1}, etag='"v1"'),
            _http_error_304("https://api.github.com/x"),
            _FakeResponse(body={"v": 1}, etag='"v1"'),  # for re-check
        ]
        self.client.get("/x")  # prime cache
        status, body = self.client.get("/x")
        self.assertEqual(status, 304)
        self.assertIsNone(body)
        self.client.get("/x")  # third request
        third_req = urlopen.call_args_list[2].args[0]
        # ETag cache was NOT cleared by the 304
        self.assertEqual(third_req.get_header("If-none-match"), '"v1"')

    @patch.object(wps.urlrequest, "urlopen")
    def test_non_304_http_error_returns_code_and_none(self, urlopen: MagicMock) -> None:
        from email.message import Message

        urlopen.side_effect = urlerror.HTTPError(
            "https://api.github.com/x",
            500,
            "Server Error",
            Message(),
            io.BytesIO(b""),
        )
        status, body = self.client.get("/x")
        self.assertEqual(status, 500)
        self.assertIsNone(body)

    @patch.object(wps.urlrequest, "urlopen")
    def test_url_error_returns_zero_status(self, urlopen: MagicMock) -> None:
        urlopen.side_effect = urlerror.URLError("boom")
        status, body = self.client.get("/x")
        self.assertEqual(status, 0)
        self.assertIsNone(body)

    @patch.object(wps.urlrequest, "urlopen")
    def test_query_params_are_urlencoded(self, urlopen: MagicMock) -> None:
        urlopen.return_value = _FakeResponse(body={}, etag='"a"')
        self.client.get("/x", {"since": "2026-01-01T00:00:00+00:00", "per_page": "100"})
        req = urlopen.call_args.args[0]
        self.assertIn("since=2026-01-01T00%3A00%3A00%2B00%3A00", req.full_url)
        self.assertIn("per_page=100", req.full_url)


class FetchCheckStateTests(unittest.TestCase):
    """Higher-level check-merge logic with the HTTP client mocked out."""

    def setUp(self) -> None:
        self.client = MagicMock()
        self.cache: dict[str, dict[str, str]] = {}

    def test_merges_check_runs_and_statuses(self) -> None:
        self.client.get.side_effect = [
            (
                200,
                {
                    "check_runs": [
                        {"name": "tests", "status": "completed", "conclusion": "success"},
                        {"name": "lint", "status": "in_progress"},
                    ]
                },
            ),
            (
                200,
                {
                    "statuses": [
                        {"context": "vercel/preview", "state": "pending"},
                        {"context": "codecov/patch", "state": "failure"},
                    ]
                },
            ),
        ]
        merged = wps.fetch_check_state(self.client, "o", "r", "sha", self.cache)
        self.assertEqual(
            merged,
            {
                "tests": "pass",
                "lint": "pending",
                "vercel/preview": "pending",
                "codecov/patch": "fail",
            },
        )

    def test_check_runs_take_precedence_on_name_collision(self) -> None:
        self.client.get.side_effect = [
            (
                200,
                {"check_runs": [{"name": "dup", "status": "completed", "conclusion": "success"}]},
            ),
            (200, {"statuses": [{"context": "dup", "state": "failure"}]}),
        ]
        merged = wps.fetch_check_state(self.client, "o", "r", "sha", self.cache)
        assert merged is not None
        self.assertEqual(merged["dup"], "pass")

    def test_304_on_both_reuses_cache(self) -> None:
        # Prime cache with a 200
        self.client.get.side_effect = [
            (
                200,
                {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}]},
            ),
            (200, {"statuses": []}),
        ]
        first = wps.fetch_check_state(self.client, "o", "r", "sha", self.cache)
        # Second pass: both endpoints return 304 → merged should still reflect prior state
        self.client.get.side_effect = [(304, None), (304, None)]
        second = wps.fetch_check_state(self.client, "o", "r", "sha", self.cache)
        self.assertEqual(first, second)

    def test_error_status_returns_none(self) -> None:
        self.client.get.side_effect = [(500, None)]
        self.assertIsNone(
            wps.fetch_check_state(self.client, "o", "r", "sha", self.cache),
        )


class FetchCommentsSinceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()

    def test_tags_source_issue_vs_review(self) -> None:
        self.client.get.side_effect = [
            (200, [{"id": 1, "user": {"login": "a"}}]),
            (200, [{"id": 2, "user": {"login": "b"}}]),
        ]
        out = wps.fetch_comments_since(self.client, "o", "r", 1, "2026-01-01T00:00:00+00:00")
        sources = [s for s, _ in out]
        self.assertEqual(sources.count("issue"), 1)
        self.assertEqual(sources.count("review"), 1)

    def test_empty_body_on_either_endpoint(self) -> None:
        self.client.get.side_effect = [(304, None), (200, [])]
        out = wps.fetch_comments_since(self.client, "o", "r", 1, "2026-01-01T00:00:00+00:00")
        self.assertEqual(out, [])


class FetchReviewsSinceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.baseline = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)

    def test_filters_by_submitted_at(self) -> None:
        self.client.get.return_value = (
            200,
            [
                {"id": 1, "submitted_at": "2026-04-12T09:00:00Z"},  # older, excluded
                {"id": 2, "submitted_at": "2026-04-12T11:00:00Z"},  # newer, included
                {"id": 3, "submitted_at": None},  # skipped
            ],
        )
        out = wps.fetch_reviews_since(self.client, "o", "r", 1, self.baseline)
        self.assertEqual([r["id"] for r in out], [2])

    def test_ignores_malformed_timestamps(self) -> None:
        self.client.get.return_value = (
            200,
            [{"id": 1, "submitted_at": "not-a-timestamp"}],
        )
        self.assertEqual(wps.fetch_reviews_since(self.client, "o", "r", 1, self.baseline), [])

    def test_non_200_returns_empty(self) -> None:
        self.client.get.return_value = (304, None)
        self.assertEqual(wps.fetch_reviews_since(self.client, "o", "r", 1, self.baseline), [])


class GetPrInfoTests(unittest.TestCase):
    @patch.object(wps, "run_gh_json")
    def test_explicit_pr_and_repo_are_passed_to_gh(self, run: MagicMock) -> None:
        run.return_value = {"number": 42, "headRefOid": "abc", "baseRepository": {}}
        info = wps.get_pr_info(42, repo="owner/name")
        self.assertEqual(info, {"number": 42, "headRefOid": "abc", "baseRepository": {}})
        args = run.call_args.args[0]
        self.assertEqual(args[0:2], ["pr", "view"])
        self.assertIn("42", args)
        self.assertIn("--repo", args)
        repo_idx = args.index("--repo")
        self.assertEqual(args[repo_idx + 1], "owner/name")

    @patch.object(wps, "run_gh_json")
    def test_no_repo_falls_back_to_cwd_resolution(self, run: MagicMock) -> None:
        run.return_value = {"number": 1}
        wps.get_pr_info(None)
        args = run.call_args.args[0]
        self.assertNotIn("--repo", args)


class MainResolutionTests(unittest.TestCase):
    """Early-exit paths when --pr / --repo / gh context can't be resolved."""

    def _run_main(self, argv: list[str]) -> tuple[int, list[str]]:
        captured: list[str] = []
        original_emit = wps.emit
        wps.emit = lambda line: captured.append(line)
        original_argv = sys.argv
        sys.argv = ["watch_pr_state.py", *argv]
        try:
            rc = wps.main()
        finally:
            wps.emit = original_emit
            sys.argv = original_argv
        return rc, captured

    @patch.object(wps, "gh_token", return_value="t")
    @patch.object(wps, "get_repo_slug", return_value=None)
    def test_missing_slug_without_repo_flag_emits_actionable_error(
        self, _slug: MagicMock, _tok: MagicMock
    ) -> None:
        rc, out = self._run_main([])
        self.assertEqual(rc, 2)
        self.assertIn("error:cannot-resolve-repo-slug-pass-repo-owner/name", out)

    @patch.object(wps, "gh_token", return_value="t")
    def test_invalid_repo_flag_is_rejected(self, _tok: MagicMock) -> None:
        rc, out = self._run_main(["--repo", "not-a-slug"])
        self.assertEqual(rc, 2)
        self.assertIn("error:invalid-repo-slug-expected-owner/name", out)

    @patch.object(wps, "gh_token", return_value="t")
    @patch.object(wps, "get_pr_info", return_value=None)
    def test_explicit_repo_but_no_pr_for_cwd_branch(self, _pr: MagicMock, _tok: MagicMock) -> None:
        rc, out = self._run_main(["--repo", "owner/name"])
        self.assertEqual(rc, 2)
        self.assertIn("error:no-pr-for-current-branch-pass-pr-number", out)

    @patch.object(wps, "gh_token", return_value="t")
    @patch.object(wps, "get_pr_info", return_value=None)
    def test_explicit_pr_and_repo_but_pr_not_found_names_the_pr(
        self, _pr: MagicMock, _tok: MagicMock
    ) -> None:
        rc, out = self._run_main(["--repo", "owner/name", "--pr", "999"])
        self.assertEqual(rc, 2)
        self.assertIn("error:pr-999-not-found-in-owner/name", out)


if __name__ == "__main__":
    unittest.main()
