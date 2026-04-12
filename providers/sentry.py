"""Sentry: error-monitoring bot comments and occasional status contexts."""

from __future__ import annotations

import re

from ._base import Provider


PROVIDER = Provider(
    name="sentry",
    detect_keywords=("sentry",),
    bot_author_patterns=(re.compile(r"(?i)^sentry"), re.compile(r"(?i)^seer")),
)
