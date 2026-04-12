from __future__ import annotations

import unittest

import providers


class RegistryDiscoveryTests(unittest.TestCase):
    def test_providers_is_populated(self) -> None:
        self.assertGreater(len(providers.PROVIDERS), 0)

    def test_all_expected_providers_are_loaded(self) -> None:
        loaded = {p.name for p in providers.PROVIDERS}
        expected = {
            "codacy",
            "codecov",
            "coderabbit",
            "cursor",
            "sentry",
            "supabase",
            "vercel",
        }
        self.assertTrue(
            expected.issubset(loaded),
            msg=f"missing providers: {expected - loaded}",
        )

    def test_underscored_modules_are_not_providers(self) -> None:
        names = {p.name for p in providers.PROVIDERS}
        self.assertNotIn("_base", names)
        self.assertNotIn("_core", names)


class DetectProviderTests(unittest.TestCase):
    def test_returns_first_matching_provider_name(self) -> None:
        self.assertEqual(
            providers.detect_provider("Configure Supabase Preview", "", ""),
            "supabase",
        )
        self.assertEqual(
            providers.detect_provider("codecov/patch", "", ""),
            "codecov",
        )
        self.assertEqual(
            providers.detect_provider("Vercel Preview", "", ""),
            "vercel",
        )

    def test_returns_fallback_when_no_match(self) -> None:
        self.assertIsNone(providers.detect_provider("tests", "CI", ""))
        self.assertEqual(
            providers.detect_provider("tests", "CI", "", fallback="external"),
            "external",
        )


class ClassifyFamilyTests(unittest.TestCase):
    def test_routes_to_correct_provider(self) -> None:
        self.assertEqual(
            providers.classify_family("supabase", "Configure Supabase Preview", "", ""),
            "supabase-preview",
        )
        self.assertEqual(
            providers.classify_family("codecov", "codecov/patch", "", ""),
            "codecov-coverage",
        )
        self.assertEqual(
            providers.classify_family("vercel", "Vercel Preview", "", ""),
            "vercel-preview",
        )

    def test_returns_none_for_unknown_provider(self) -> None:
        self.assertIsNone(
            providers.classify_family("nope", "anything", "", ""),
        )

    def test_returns_none_when_provider_has_no_rule_match(self) -> None:
        self.assertIsNone(
            providers.classify_family("codacy", "Codacy", "", ""),
        )


class AllFailureMarkersTests(unittest.TestCase):
    def test_aggregates_markers_from_all_providers(self) -> None:
        markers = providers.all_failure_markers()
        names = {name for name, _ in markers}
        # Supabase currently contributes six markers; registry should include them all
        self.assertIn("MIGRATIONS_FAILED", names)
        self.assertIn("TIMEOUT_WAITING_FOR_BRANCH", names)
        self.assertIn("FAILED_TO_SET_SECRETS", names)


class BotAuthorPatternsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patterns = providers.bot_author_patterns()

    def _is_bot(self, username: str) -> bool:
        return any(p.search(username) for p in self.patterns)

    def test_includes_generic_defaults(self) -> None:
        self.assertTrue(self._is_bot("dependabot"))
        self.assertTrue(self._is_bot("renovate"))
        self.assertTrue(self._is_bot("github-actions"))
        self.assertTrue(self._is_bot("copilot"))
        self.assertTrue(self._is_bot("anything[bot]"))
        self.assertTrue(self._is_bot("somebot"))

    def test_includes_provider_contributed_patterns(self) -> None:
        self.assertTrue(self._is_bot("codecov[bot]"))
        self.assertTrue(self._is_bot("sentry-bot"))
        self.assertTrue(self._is_bot("seer"))
        self.assertTrue(self._is_bot("cursor"))
        self.assertTrue(self._is_bot("bugbot"))
        self.assertTrue(self._is_bot("coderabbitai"))

    def test_human_reviewers_not_matched(self) -> None:
        self.assertFalse(self._is_bot("gerokeller"))
        self.assertFalse(self._is_bot("alice"))


class BuildRecoveryHintRoutingTests(unittest.TestCase):
    def test_routes_to_supabase_for_supabase_preview(self) -> None:
        hint = providers.build_recovery_hint(
            "supabase", "supabase-preview", "fail", ["MIGRATIONS_FAILED"]
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint["classification"], "supabase-preview")

    def test_routes_to_codecov_for_codecov_coverage(self) -> None:
        hint = providers.build_recovery_hint("codecov", "codecov-coverage", "fail", [])
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertEqual(hint["classification"], "codecov-coverage")

    def test_returns_none_for_unknown_provider(self) -> None:
        self.assertIsNone(
            providers.build_recovery_hint("nope", "family", "fail", []),
        )

    def test_returns_none_when_provider_has_no_hint(self) -> None:
        # vercel provider currently has no recovery builder
        self.assertIsNone(
            providers.build_recovery_hint("vercel", "vercel-preview", "fail", []),
        )

    def test_returns_none_when_provider_name_is_none(self) -> None:
        self.assertIsNone(providers.build_recovery_hint(None, "x", "fail", []))


if __name__ == "__main__":
    unittest.main()
