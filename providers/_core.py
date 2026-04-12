"""Generic bot-author patterns that apply regardless of which providers are
enabled. Provider modules may contribute additional product-specific patterns
(e.g. ``^codecov``) via :attr:`Provider.bot_author_patterns`.
"""

from __future__ import annotations

import re

GENERIC_BOT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bot$"),
    re.compile(r"(?i)\[bot\]$"),
    re.compile(r"(?i)^dependabot"),
    re.compile(r"(?i)^renovate"),
    re.compile(r"(?i)^github-actions"),
    re.compile(r"(?i)^mergify"),
    re.compile(r"(?i)^semantic-release"),
    re.compile(r"(?i)^sonarcloud"),
    re.compile(r"(?i)^snyk"),
    re.compile(r"(?i)^copilot"),
)
