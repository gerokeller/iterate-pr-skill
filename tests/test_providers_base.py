from __future__ import annotations

import re
import unittest

from providers._base import Provider, RecoveryHint


class RecoveryHintTests(unittest.TestCase):
    def test_to_dict_serializes_tuple_steps_as_list(self) -> None:
        hint = RecoveryHint(
            classification="x",
            summary="s",
            recommended_steps=("a", "b", "c"),
            stop_only_after="z",
        )
        d = hint.to_dict()
        self.assertEqual(d["classification"], "x")
        self.assertEqual(d["summary"], "s")
        self.assertEqual(d["recommended_steps"], ["a", "b", "c"])
        self.assertIsInstance(d["recommended_steps"], list)
        self.assertEqual(d["stop_only_after"], "z")


class ProviderDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Provider(name="demo", detect_keywords=("demo", "sample"))

    def test_detects_is_case_insensitive(self) -> None:
        self.assertTrue(self.p.detects("DEMO Build", "", ""))
        self.assertTrue(self.p.detects("run", "", "https://ci/demo/12"))
        self.assertTrue(self.p.detects("", "Sample workflow", ""))

    def test_detects_false_when_no_keyword_appears(self) -> None:
        self.assertFalse(self.p.detects("tests", "CI", "https://ci/run/1"))

    def test_detects_checks_name_workflow_and_link_combined(self) -> None:
        self.assertTrue(self.p.detects("tests", "", "https://ci.demo.local/run/1"))


class ProviderFamilyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Provider(
            name="demo",
            detect_keywords=("demo",),
            family_rules=(
                (("demo", "deploy"), "demo-deploy"),
                (("demo",), "demo-generic"),
            ),
        )

    def test_classify_family_picks_first_matching_rule(self) -> None:
        self.assertEqual(self.p.classify_family("Demo Deploy", "", ""), "demo-deploy")

    def test_classify_family_falls_through_to_later_rule(self) -> None:
        self.assertEqual(self.p.classify_family("Demo Audit", "", ""), "demo-generic")

    def test_classify_family_returns_none_when_no_rule_matches(self) -> None:
        self.assertIsNone(self.p.classify_family("unrelated", "", ""))

    def test_classify_family_requires_all_keywords_in_tuple(self) -> None:
        # "deploy" without "demo" should not match demo-deploy rule
        p = Provider(
            name="demo",
            detect_keywords=("demo",),
            family_rules=((("demo", "deploy"), "demo-deploy"),),
        )
        self.assertIsNone(p.classify_family("other deploy", "", ""))


class ProviderRecoveryBuilderTests(unittest.TestCase):
    def test_build_recovery_hint_returns_none_without_builder(self) -> None:
        p = Provider(name="demo", detect_keywords=("demo",))
        self.assertIsNone(p.build_recovery_hint("demo", "fail", []))

    def test_build_recovery_hint_calls_builder(self) -> None:
        def builder(family, status, markers):
            return RecoveryHint(
                classification=family or "",
                summary=f"{status}:{len(markers)}",
                recommended_steps=(),
                stop_only_after="",
            )

        p = Provider(name="demo", detect_keywords=("demo",), recovery_builder=builder)
        hint = p.build_recovery_hint("demo-deploy", "fail", ["A", "B"])
        self.assertIsNotNone(hint)
        assert hint is not None  # for type narrowing
        self.assertEqual(hint.classification, "demo-deploy")
        self.assertEqual(hint.summary, "fail:2")


class ProviderFailureMarkerTests(unittest.TestCase):
    def test_failure_marker_patterns_default_empty(self) -> None:
        p = Provider(name="demo", detect_keywords=("demo",))
        self.assertEqual(p.failure_marker_patterns, ())

    def test_failure_marker_patterns_preserved(self) -> None:
        marker = ("X", re.compile(r"\bX\b"))
        p = Provider(
            name="demo",
            detect_keywords=("demo",),
            failure_marker_patterns=(marker,),
        )
        self.assertEqual(p.failure_marker_patterns, (marker,))


if __name__ == "__main__":
    unittest.main()
