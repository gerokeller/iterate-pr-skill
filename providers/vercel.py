"""Vercel: preview deployments and related status contexts."""

from __future__ import annotations

from ._base import Provider


PROVIDER = Provider(
    name="vercel",
    detect_keywords=("vercel",),
    family_rules=((("vercel", "preview"), "vercel-preview"),),
)
