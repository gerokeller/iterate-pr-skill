"""Provider interface for pluggable PR check handling.

Each provider module in this package exports a ``PROVIDER`` instance of
:class:`Provider`. The registry in :mod:`providers.__init__` auto-discovers
them on import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class RecoveryHint:
    """Structured recovery guidance attached to a failing check."""

    classification: str
    summary: str
    recommended_steps: tuple[str, ...]
    stop_only_after: str

    def to_dict(self) -> dict:
        return {
            "classification": self.classification,
            "summary": self.summary,
            "recommended_steps": list(self.recommended_steps),
            "stop_only_after": self.stop_only_after,
        }


# Type alias lives at module scope, so PEP 604 ``X | None`` syntax would be
# evaluated eagerly and break on Python 3.9. Use ``Optional`` for the alias.
# ``from __future__ import annotations`` only defers *annotations*, not aliases.
RecoveryBuilder = Callable[
    [Optional[str], str, list[str]],
    Optional["RecoveryHint"],
]


@dataclass(frozen=True)
class Provider:
    """Declarative description of a CI/status provider.

    A ``Provider`` contributes the rules needed to (a) detect its checks and
    status contexts by name, (b) classify them into a sub-family for recovery,
    (c) extract stable failure markers from log text, (d) mark its bot accounts
    as automated commenters, and (e) emit a recovery hint for actionable
    failures.

    All fields are optional except ``name`` and ``detect_keywords``. Providers
    that only want detection (e.g. to tag checks for human visibility) can omit
    the rest.
    """

    name: str
    detect_keywords: tuple[str, ...]
    family_rules: tuple[tuple[tuple[str, ...], str], ...] = ()
    failure_marker_patterns: tuple[tuple[str, re.Pattern[str]], ...] = ()
    bot_author_patterns: tuple[re.Pattern[str], ...] = ()
    recovery_builder: RecoveryBuilder | None = field(default=None)

    def detects(self, name: str, workflow: str, link: str) -> bool:
        haystack = f"{name} {workflow} {link}".lower()
        return any(kw in haystack for kw in self.detect_keywords)

    def classify_family(self, name: str, workflow: str, link: str) -> str | None:
        haystack = f"{name} {workflow} {link}".lower()
        for keywords, family in self.family_rules:
            if all(kw in haystack for kw in keywords):
                return family
        return None

    def build_recovery_hint(
        self,
        family: str | None,
        status: str,
        failure_markers: list[str],
    ) -> RecoveryHint | None:
        if self.recovery_builder is None:
            return None
        return self.recovery_builder(family, status, failure_markers)
