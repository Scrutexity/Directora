"""Feature 2 — iOS Widget status feed.

GET /api/widget/status
    Returns agent health, uptime, last action, and pending alert count
    in a single call optimised for iOS WidgetKit refresh budgets.
    No auth required — designed for home-screen widget polling.
    (Bind the server to localhost or behind a VPN; don't expose publicly.)
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/widget", tags=["widget"])


class AgentStatus(BaseModel):
    name: str
    healthy: bool
    uptime_seconds: Optional[int] = None
    last_action: Optional[str] = None
    last_action_at: Optional[str] = None
    pending_alerts: int = 0


class WidgetStatusResponse(BaseModel):
    agents: list[AgentStatus]
    pending_alerts: int
    updated_at: str
    server_ok: bool


def _mock_agent_statuses() -> list[AgentStatus]:
    """Stub — replace with real Hermes agent health queries."""
    return [
        AgentStatus(
            name="sourcing-intel",
            healthy=True,
            uptime_seconds=3600,
            last_action="sweep completed",
            last_action_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            pending_alerts=0,
        ),
        AgentStatus(
            name="daily-brief",
            healthy=True,
            uptime_seconds=86400,
            last_action="brief compiled",
            last_action_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            pending_alerts=0,
        ),
        AgentStatus(
            name="competitor-monitor",
            healthy=True,
            uptime_seconds=7200,
            last_action="signals checked",
            last_action_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            pending_alerts=0,
        ),
    ]


@router.get("/status", response_model=WidgetStatusResponse)
async def widget_status() -> WidgetStatusResponse:
    """iOS Widget endpoint — returns all agent statuses in one shot.

    WidgetKit calls this every ~15 min (system-controlled). Keep it fast;
    do not block on slow Hermes queries — return cached state if needed.
    """
    agents = _mock_agent_statuses()
    total_alerts = sum(a.pending_alerts for a in agents)

    return WidgetStatusResponse(
        agents=agents,
        pending_alerts=total_alerts,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        server_ok=True,
    )


__all__ = ["router"]
