"""Cursor bugbot and related AI review bot comments."""

from __future__ import annotations

import re

from ._base import Provider

PROVIDER = Provider(
    name="cursor",
    detect_keywords=("cursor",),
    bot_author_patterns=(re.compile(r"(?i)^cursor"), re.compile(r"(?i)^bugbot")),
)
