from __future__ import annotations

import unittest

from providers.codacy import PROVIDER as CODACY
from providers.coderabbit import PROVIDER as CODERABBIT
from providers.cursor import PROVIDER as CURSOR
from providers.sentry import PROVIDER as SENTRY
from providers.vercel import PROVIDER as VERCEL


class VercelTests(unittest.TestCase):
    def test_detection(self) -> None:
        self.assertTrue(VERCEL.detects("Vercel Preview", "", ""))
        self.assertFalse(VERCEL.detects("tests", "CI", ""))

    def test_family(self) -> None:
        self.assertEqual(VERCEL.classify_family("Vercel Preview", "", ""), "vercel-preview")
        self.assertIsNone(VERCEL.classify_family("Vercel Deploy", "", ""))

    def test_no_recovery_builder(self) -> None:
        self.assertIsNone(VERCEL.build_recovery_hint("vercel-preview", "fail", []))


class CodacyTests(unittest.TestCase):
    def test_detection(self) -> None:
        self.assertTrue(CODACY.detects("Codacy", "", ""))

    def test_no_family_rules(self) -> None:
        self.assertIsNone(CODACY.classify_family("Codacy", "", ""))

    def test_no_bot_patterns(self) -> None:
        self.assertEqual(CODACY.bot_author_patterns, ())


class CodeRabbitTests(unittest.TestCase):
    def test_detection(self) -> None:
        self.assertTrue(CODERABBIT.detects("coderabbit", "", ""))

    def test_bot_pattern_matches_author(self) -> None:
        self.assertTrue(
            any(p.search("coderabbitai") for p in CODERABBIT.bot_author_patterns),
        )
        self.assertTrue(
            any(p.search("coderabbit[bot]") for p in CODERABBIT.bot_author_patterns),
        )


class SentryTests(unittest.TestCase):
    def test_detection(self) -> None:
        self.assertTrue(SENTRY.detects("sentry-io", "", ""))

    def test_bot_patterns_cover_sentry_and_seer(self) -> None:
        self.assertTrue(any(p.search("sentry-io") for p in SENTRY.bot_author_patterns))
        self.assertTrue(any(p.search("seer") for p in SENTRY.bot_author_patterns))


class CursorTests(unittest.TestCase):
    def test_detection(self) -> None:
        self.assertTrue(CURSOR.detects("cursor", "", ""))

    def test_bot_patterns_cover_cursor_and_bugbot(self) -> None:
        self.assertTrue(any(p.search("cursor[bot]") for p in CURSOR.bot_author_patterns))
        self.assertTrue(any(p.search("bugbot") for p in CURSOR.bot_author_patterns))


if __name__ == "__main__":
    unittest.main()
