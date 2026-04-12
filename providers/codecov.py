"""Codecov: code-coverage status contexts and bot comments.

See ``codecov.md`` for agent-facing recovery guidance.
"""

from __future__ import annotations

import re

from ._base import Provider, RecoveryHint


def _recovery(
    family: str | None, status: str, _markers: list[str]
) -> RecoveryHint | None:
    if family != "codecov-coverage" or status not in {"fail", "cancel", "pending"}:
        return None
    return RecoveryHint(
        classification="codecov-coverage",
        summary=(
            "Codecov coverage checks are merge blockers when they fail and GitHub "
            "still reports the PR as blocked."
        ),
        recommended_steps=(
            "Open the Codecov details URL and capture whether the failure is patch coverage, project coverage, or upload/config related.",
            "If patch or project coverage failed, identify the changed lines reducing coverage and add or adjust tests locally before pushing.",
            "If the Codecov status looks stale or upload-related, inspect the paired CI workflow output for upload/config failures before retrying.",
            "Do not describe a failing Codecov check as informational unless GitHub explicitly reports the PR as merge-ready.",
        ),
        stop_only_after=(
            "Inspecting the Codecov details and exhausting the repository-side "
            "coverage or upload fixes available from the current branch"
        ),
    )


PROVIDER = Provider(
    name="codecov",
    detect_keywords=("codecov",),
    family_rules=((("codecov",), "codecov-coverage"),),
    bot_author_patterns=(re.compile(r"(?i)^codecov"),),
    recovery_builder=_recovery,
)
