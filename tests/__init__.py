"""Test package. Adds the skill root and ``scripts/`` to ``sys.path`` so tests
can import ``providers`` and the bare script modules without installation.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _entry in (_ROOT, os.path.join(_ROOT, "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
