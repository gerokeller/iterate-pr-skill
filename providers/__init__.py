"""Pluggable provider registry.

Discovers every non-underscored ``*.py`` module in this package, expects each
to export a ``PROVIDER`` instance of :class:`Provider`, and exposes an
aggregated API consumed by the ``fetch_pr_checks`` / ``fetch_pr_feedback``
scripts.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from ._base import Provider, RecoveryHint
from ._core import GENERIC_BOT_PATTERNS


def _discover() -> list[Provider]:
    found: list[Provider] = []
    pkg_dir = Path(__file__).parent
    for entry in sorted(pkg_dir.iterdir()):
        if entry.suffix != ".py" or entry.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{entry.stem}")
        provider = getattr(module, "PROVIDER", None)
        if isinstance(provider, Provider):
            found.append(provider)
    return found


PROVIDERS: list[Provider] = _discover()


def detect_provider(name: str, workflow: str, link: str, fallback: str | None = None) -> str | None:
    """Return the first provider whose detection keywords match, else fallback."""
    for provider in PROVIDERS:
        if provider.detects(name, workflow, link):
            return provider.name
    return fallback


def classify_family(provider_name: str, name: str, workflow: str, link: str) -> str | None:
    for provider in PROVIDERS:
        if provider.name == provider_name:
            return provider.classify_family(name, workflow, link)
    return None


def all_failure_markers() -> list[tuple[str, re.Pattern[str]]]:
    markers: list[tuple[str, re.Pattern[str]]] = []
    for provider in PROVIDERS:
        markers.extend(provider.failure_marker_patterns)
    return markers


def bot_author_patterns() -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = list(GENERIC_BOT_PATTERNS)
    for provider in PROVIDERS:
        patterns.extend(provider.bot_author_patterns)
    return patterns


def build_recovery_hint(
    provider_name: str | None,
    family: str | None,
    status: str,
    failure_markers: list[str],
) -> dict | None:
    if not provider_name:
        return None
    for provider in PROVIDERS:
        if provider.name != provider_name:
            continue
        hint = provider.build_recovery_hint(family, status, failure_markers)
        if hint is not None:
            return hint.to_dict()
    return None


__all__ = [
    "PROVIDERS",
    "Provider",
    "RecoveryHint",
    "all_failure_markers",
    "bot_author_patterns",
    "build_recovery_hint",
    "classify_family",
    "detect_provider",
]
