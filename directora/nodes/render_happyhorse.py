"""Reference HappyHorse fallback renderer.

The real v3.0 implementation lives in your existing repo; this stub
exists so the v3.1 add-on tests run standalone. It returns a deterministic
fallback payload that the Quality Render Step relabels to "Fallback
Render Draft".
"""
from __future__ import annotations

from typing import Any


def render(state: Any) -> dict:
    shot_count = len(getattr(state, "shot_plan", []) or [])
    return {
        "render": {
            "engine": "happyhorse",
            "video_url": None,
            "frames": [],
            "duration_s": 0.0,
            "shot_count": shot_count,
        }
    }
