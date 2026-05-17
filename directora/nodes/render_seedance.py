"""
Quality Render Step (optional, non-blocking).

Clinic-facing label: "Quality Render Step". The fallback path is labeled
"Fallback Render Draft". The internal MCP call still targets Higgsfield's
Seedance model — that name is acceptable as an engine identifier in the
ledger, but clinic-facing surfaces should not lead with it.

Critical rule: rendering is OPTIONAL. A render failure must never block
the Authority Brief, the Authority Review Summary, the claim-risk notes,
the content asset export, or the Owner Brief. Any error we catch is
recorded in the Governed Workflow Ledger as `render_fallback` and we
return the fallback render output instead.

Routing:
    - tier == "quality" or FORCE_SEEDANCE=1 -> attempt the quality render
    - otherwise                            -> use the existing fallback
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

# These imports are kept lazy-tolerant: the MCPClient module may not be
# importable in environments that don't ship the MCP wrapper. We catch
# ImportError at call time and treat it as a render fallback.
try:
    from directora.clients.mcp import MCPClient, MCPError  # type: ignore
except Exception:  # pragma: no cover - defensive, depends on host env
    MCPClient = None  # type: ignore

    class MCPError(Exception):
        """Local stand-in if the MCP wrapper isn't available."""

# HappyHorse is the existing fallback renderer in v3.0.
try:
    from directora.nodes import render_happyhorse  # type: ignore
except Exception:  # pragma: no cover
    render_happyhorse = None  # type: ignore

from directora.telemetry.outcome import record_outcome

log = logging.getLogger(__name__)

HIGGSFIELD_SERVER = os.getenv("HIGGSFIELD_MCP_SERVER", "higgsfield")
SEEDANCE_TOOL = os.getenv("HIGGSFIELD_SEEDANCE_TOOL", "seedance.render")
SEEDANCE_TIMEOUT_S = float(os.getenv("SEEDANCE_TIMEOUT_S", "120"))

# Clinic-facing labels surfaced on render results.
QUALITY_RENDER_LABEL = "Quality Render Step"
FALLBACK_RENDER_LABEL = "Fallback Render Draft"


def _should_attempt_quality(state: Any) -> bool:
    if os.getenv("FORCE_SEEDANCE") == "1":
        return True
    if getattr(state, "tier", "fast") != "quality":
        return False
    return bool(getattr(state, "use_seedance", True))


def _build_quality_params(state: Any) -> dict:
    shots = []
    for s in getattr(state, "shot_plan", []) or []:
        shots.append(
            {
                "duration_s": getattr(s, "duration_s", 2.0),
                "prompt": getattr(s, "visual_prompt", ""),
                "camera": getattr(s, "camera", "static"),
                "subject_ref": getattr(s, "subject_ref", None),
            }
        )
    return {
        "shots": shots,
        "global_prompt": getattr(state, "prompt", ""),
        "aspect_ratio": getattr(state, "aspect_ratio", "9:16"),
        "fps": getattr(state, "fps", 24),
        "audio": getattr(state, "audio_spec", None),
    }


def _fallback(state: Any, reason: str | None = None) -> dict:
    """Run the HappyHorse fallback renderer (or emit a safe stub) and tag
    the result with the clinic-facing label."""
    started = time.time()
    if render_happyhorse is not None:
        try:
            base = render_happyhorse.render(state)
        except Exception as exc:  # never let fallback raise
            log.exception("HappyHorse fallback raised; emitting empty render")
            record_outcome(
                state,
                kind="render_fallback",
                engine="happyhorse",
                reason=f"fallback_exception: {exc}",
                latency_s=time.time() - started,
            )
            return {
                "render": {
                    "engine": "fallback",
                    "label": FALLBACK_RENDER_LABEL,
                    "video_url": None,
                    "frames": [],
                    "skipped": True,
                    "reason": "Fallback render unavailable; outputs unaffected.",
                }
            }
    else:
        # No fallback module available — emit a stub so the pipeline continues.
        return {
            "render": {
                "engine": "fallback",
                "label": FALLBACK_RENDER_LABEL,
                "video_url": None,
                "frames": [],
                "skipped": True,
                "reason": "No fallback renderer registered.",
            }
        }

    latency_s = time.time() - started
    record_outcome(
        state,
        kind="render_fallback" if reason else "render_ok",
        engine="happyhorse",
        latency_s=latency_s,
        reason=reason,
    )
    # Normalise the shape into the v3.1 contract.
    render = dict(base.get("render", {}))
    render.setdefault("engine", "happyhorse")
    render["label"] = FALLBACK_RENDER_LABEL
    render["skipped"] = False
    return {"render": render}


def render(state: Any) -> dict:
    """LangGraph node entry point.

    Always returns a state delta with a `render` key. The pipeline must
    keep moving even if rendering fails entirely.
    """
    if not _should_attempt_quality(state):
        log.info("Quality Render Step skipped (tier=%s).", getattr(state, "tier", "?"))
        return _fallback(state)

    if MCPClient is None:
        return _fallback(state, reason="MCP client unavailable")

    started = time.time()
    try:
        client = MCPClient()
        result = client.call(
            server=HIGGSFIELD_SERVER,
            tool=SEEDANCE_TOOL,
            params=_build_quality_params(state),
            timeout_s=SEEDANCE_TIMEOUT_S,
        )
    except MCPError as exc:
        log.warning("Quality Render Step failed: %s — using Fallback Render Draft", exc)
        return _fallback(state, reason=str(exc))
    except Exception as exc:  # any other failure -> safe fallback
        log.exception("Quality Render Step raised unexpectedly")
        return _fallback(state, reason=f"unexpected: {exc}")

    latency_s = time.time() - started
    record_outcome(
        state,
        kind="render_ok",
        engine="seedance",
        latency_s=latency_s,
        shot_count=len(getattr(state, "shot_plan", []) or []),
    )
    return {
        "render": {
            "engine": "seedance",
            "label": QUALITY_RENDER_LABEL,
            "video_url": result.get("video_url"),
            "frames": result.get("frames", []),
            "duration_s": result.get("duration_s"),
            "skipped": False,
            "raw": result,
        }
    }
