from __future__ import annotations

import unittest

from providers.codecov import PROVIDER


class CodecovDetectionTests(unittest.TestCase):
    def test_detects_codecov_status_context(self) -> None:
        self.assertTrue(PROVIDER.detects("codecov/patch", "", ""))
        self.assertTrue(PROVIDER.detects("codecov/project", "", ""))

    def test_does_not_detect_unrelated(self) -> None:
        self.assertFalse(PROVIDER.detects("tests", "CI", ""))


class CodecovFamilyTests(unittest.TestCase):
    def test_family_is_coverage(self) -> None:
        self.assertEqual(
            PROVIDER.classify_family("codecov/patch", "", ""),
            "codecov-coverage",
        )


class CodecovBotPatternsTests(unittest.TestCase):
    def test_bot_pattern_matches_codecov_accounts(self) -> None:
        patterns = PROVIDER.bot_author_patterns
        self.assertTrue(any(p.search("codecov[bot]") for p in patterns))
        self.assertTrue(any(p.search("codecov-commenter") for p in patterns))


class CodecovRecoveryHintTests(unittest.TestCase):
    def test_returns_none_for_wrong_family(self) -> None:
        self.assertIsNone(PROVIDER.build_recovery_hint("other", "fail", []))

    def test_returns_none_for_pass(self) -> None:
        self.assertIsNone(PROVIDER.build_recovery_hint("codecov-coverage", "pass", []))

    def test_returns_hint_for_fail(self) -> None:
        hint = PROVIDER.build_recovery_hint("codecov-coverage", "fail", [])
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint.classification, "codecov-coverage")
        self.assertIn("Codecov", hint.summary)
        self.assertTrue(hint.recommended_steps)
        joined = " ".join(hint.recommended_steps).lower()
        self.assertIn("patch coverage", joined)
        self.assertIn("project coverage", joined)

    def test_returns_hint_for_pending_and_cancel(self) -> None:
        self.assertIsNotNone(
            PROVIDER.build_recovery_hint("codecov-coverage", "pending", []),
        )
        self.assertIsNotNone(
            PROVIDER.build_recovery_hint("codecov-coverage", "cancel", []),
        )


if __name__ == "__main__":
    unittest.main()
