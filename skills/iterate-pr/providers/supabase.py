"""Supabase: database + auth + preview-branch provisioning.

See ``supabase.md`` for agent-facing recovery guidance.
"""

from __future__ import annotations

import re

from ._base import Provider, RecoveryHint

_FAILURE_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MIGRATIONS_FAILED", re.compile(r"\bMIGRATIONS_FAILED\b", re.IGNORECASE)),
    ("TIMEOUT_WAITING_FOR_BRANCH", re.compile(r"Timeout waiting for branch", re.IGNORECASE)),
    ("FAILED_TO_SET_SECRETS", re.compile(r"Failed to set secrets", re.IGNORECASE)),
    (
        "AUTH_HOOK_CONFIGURATION_FAILED",
        re.compile(r"Auth hook configuration failed", re.IGNORECASE),
    ),
    (
        "FAILED_TO_CREATE_SUPABASE_BRANCH",
        re.compile(r"Failed to create Supabase branch", re.IGNORECASE),
    ),
    (
        "FAILED_TO_LIST_SUPABASE_BRANCHES",
        re.compile(r"Failed to list Supabase branches", re.IGNORECASE),
    ),
)


def _recovery(family: str | None, status: str, markers: list[str]) -> RecoveryHint | None:
    if family != "supabase-preview" or status not in {"fail", "cancel", "pending"}:
        return None

    summary = (
        "Inspect the exact Preview workflow output and Supabase status details "
        "before classifying this as external-only."
    )
    if "MIGRATIONS_FAILED" in markers:
        summary = (
            "Supabase preview provisioning reported MIGRATIONS_FAILED; this can be "
            "a real migration/config problem or a stale preview branch."
        )
    elif "TIMEOUT_WAITING_FOR_BRANCH" in markers:
        summary = "Supabase preview provisioning timed out waiting for the branch to become ready."

    return RecoveryHint(
        classification="supabase-preview",
        summary=summary,
        recommended_steps=(
            "Inspect the exact job logs or details URL before deciding the failure is external-only.",
            "If the output points to migrations, schema drift, or preview configuration, fix the repository issue locally and validate the relevant migration/test surface.",
            "If the output points to stale or stuck preview provisioning, rerun the Preview workflow once.",
            "If rerun does not clear the stale preview state, close and reopen the PR once to trigger preview provisioning again.",
        ),
        stop_only_after=(
            "Inspecting the failure output and exhausting one rerun plus one PR "
            "reopen recovery attempt"
        ),
    )


PROVIDER = Provider(
    name="supabase",
    detect_keywords=("supabase",),
    family_rules=((("supabase", "preview"), "supabase-preview"),),
    failure_marker_patterns=_FAILURE_MARKERS,
    recovery_builder=_recovery,
)
