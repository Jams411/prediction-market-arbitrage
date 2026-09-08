"""Test bootstrap.

Adds ``scripts/`` to ``sys.path`` so the standalone, non-packaged observation
scripts (e.g. ``observe_kalshi_demo``) can be imported and unit-tested. mypy
resolves the same modules via ``mypy_path`` in ``pyproject.toml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
