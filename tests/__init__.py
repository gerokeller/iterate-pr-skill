"""Test package. Adds the skill directory and its ``scripts/`` subdir to
``sys.path`` so tests can import ``providers`` and the bare script modules
without installation.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_DIR = os.path.join(_REPO_ROOT, "skills", "iterate-pr")
for _entry in (_SKILL_DIR, os.path.join(_SKILL_DIR, "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
