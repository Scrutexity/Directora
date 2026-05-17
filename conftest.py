"""Make the scrutexity_addon package importable when running pytest from
either the repo root or the addon directory."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
