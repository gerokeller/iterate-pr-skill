"""CodeRabbit: AI code review status contexts and bot comments."""

from __future__ import annotations

import re

from ._base import Provider


PROVIDER = Provider(
    name="coderabbit",
    detect_keywords=("coderabbit",),
    bot_author_patterns=(re.compile(r"(?i)^coderabbit"),),
)
