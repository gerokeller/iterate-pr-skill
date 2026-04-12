from __future__ import annotations

import unittest

from providers.supabase import PROVIDER


class SupabaseDetectionTests(unittest.TestCase):
    def test_detects_by_name(self) -> None:
        self.assertTrue(PROVIDER.detects("Configure Supabase Preview", "", ""))
        self.assertTrue(PROVIDER.detects("supabase", "", ""))

    def test_detects_case_insensitive(self) -> None:
        self.assertTrue(PROVIDER.detects("SUPABASE", "", ""))

    def test_does_not_detect_unrelated(self) -> None:
        self.assertFalse(PROVIDER.detects("tests", "CI", ""))


class SupabaseFamilyTests(unittest.TestCase):
    def test_preview_family(self) -> None:
        self.assertEqual(
            PROVIDER.classify_family("Configure Supabase Preview", "", ""),
            "supabase-preview",
        )
        self.assertEqual(
            PROVIDER.classify_family("Ensure Supabase Preview Branch", "", ""),
            "supabase-preview",
        )

    def test_non_preview_supabase_check_has_no_family(self) -> None:
        self.assertIsNone(PROVIDER.classify_family("Supabase Types", "", ""))


class SupabaseFailureMarkersTests(unittest.TestCase):
    def test_six_markers_defined(self) -> None:
        names = {n for n, _ in PROVIDER.failure_marker_patterns}
        self.assertEqual(
            names,
            {
                "MIGRATIONS_FAILED",
                "TIMEOUT_WAITING_FOR_BRANCH",
                "FAILED_TO_SET_SECRETS",
                "AUTH_HOOK_CONFIGURATION_FAILED",
                "FAILED_TO_CREATE_SUPABASE_BRANCH",
                "FAILED_TO_LIST_SUPABASE_BRANCHES",
            },
        )

    def test_markers_match_log_phrases(self) -> None:
        patterns = {n: p for n, p in PROVIDER.failure_marker_patterns}
        self.assertIsNotNone(patterns["MIGRATIONS_FAILED"].search("::error MIGRATIONS_FAILED"))
        self.assertIsNotNone(
            patterns["TIMEOUT_WAITING_FOR_BRANCH"].search("Timeout waiting for branch"),
        )
        self.assertIsNotNone(
            patterns["FAILED_TO_SET_SECRETS"].search("Failed to set secrets"),
        )


class SupabaseRecoveryHintTests(unittest.TestCase):
    def test_returns_none_for_non_preview_family(self) -> None:
        self.assertIsNone(PROVIDER.build_recovery_hint("supabase-other", "fail", []))

    def test_returns_none_for_passing_status(self) -> None:
        self.assertIsNone(PROVIDER.build_recovery_hint("supabase-preview", "pass", []))

    def test_generic_preview_failure(self) -> None:
        hint = PROVIDER.build_recovery_hint("supabase-preview", "fail", [])
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.classification, "supabase-preview")
        self.assertIn("Inspect", hint.summary)
        self.assertTrue(hint.recommended_steps)
        self.assertIn("rerun", " ".join(hint.recommended_steps).lower())
        self.assertIn("reopen", " ".join(hint.recommended_steps).lower())

    def test_migrations_failed_summary(self) -> None:
        hint = PROVIDER.build_recovery_hint(
            "supabase-preview", "fail", ["MIGRATIONS_FAILED"]
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("MIGRATIONS_FAILED", hint.summary)

    def test_timeout_summary(self) -> None:
        hint = PROVIDER.build_recovery_hint(
            "supabase-preview", "cancel", ["TIMEOUT_WAITING_FOR_BRANCH"]
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("timed out", hint.summary.lower())

    def test_migrations_precedence_over_timeout(self) -> None:
        hint = PROVIDER.build_recovery_hint(
            "supabase-preview",
            "fail",
            ["MIGRATIONS_FAILED", "TIMEOUT_WAITING_FOR_BRANCH"],
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("MIGRATIONS_FAILED", hint.summary)

    def test_pending_status_still_produces_hint(self) -> None:
        # Pending preview checks should still get guidance to inspect.
        hint = PROVIDER.build_recovery_hint("supabase-preview", "pending", [])
        self.assertIsNotNone(hint)


if __name__ == "__main__":
    unittest.main()
