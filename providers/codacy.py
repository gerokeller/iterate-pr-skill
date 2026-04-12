"""Codacy: static-analysis status contexts."""

from __future__ import annotations

from ._base import Provider


PROVIDER = Provider(
    name="codacy",
    detect_keywords=("codacy",),
)
