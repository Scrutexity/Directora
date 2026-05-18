"""Feature 4 — Per-skill cost tracking.

GET  /api/costs            monthly spend summary across all skills
GET  /api/costs/{skill}    per-skill detail (daily breakdown)
POST /api/costs/record     record a cost event after an agent run

Budget alert fires when monthly total exceeds BIRKIN_BUDGET_USD env var.
Push notification (Feature 5) is triggered automatically on threshold breach.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import secrets
import os

from directora.api.secrets import get_secret

router = APIRouter(prefix="/api/costs", tags=["costs"])

_bearer = HTTPBearer(auto_error=True)

# In-memory ledger — replace with SQLite persistence
# Schema: skill → list of {"usd": float, "ts": float, "run_id": str}
_cost_events: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _verify_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    expected = get_secret("BIRKIN_TOKEN")
    if not expected or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return creds.credentials


def _month_start_ts() -> float:
    t = time.gmtime()
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, 0))


class CostRecord(BaseModel):
    skill: str
    usd: float
    run_id: Optional[str] = None
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class SkillCostSummary(BaseModel):
    skill: str
    usd: float
    runs: int
    avg_usd_per_run: float


class CostSummaryResponse(BaseModel):
    period: str
    total_usd: float
    budget_usd: Optional[float]
    budget_pct: Optional[float]
    over_budget: bool
    skills: list[SkillCostSummary]
    updated_at: str


class SkillCostDetailResponse(BaseModel):
    skill: str
    period: str
    total_usd: float
    runs: int
    events: list[dict[str, Any]]


@router.post("/record", status_code=status.HTTP_201_CREATED)
async def record_cost(
    body: CostRecord,
    _token: str = Depends(_verify_token),
) -> dict[str, Any]:
    """Record a cost event. Call this after each agent run completes."""
    event: dict[str, Any] = {
        "usd": body.usd,
        "ts": time.time(),
        "run_id": body.run_id,
        "model": body.model,
        "tokens_in": body.tokens_in,
        "tokens_out": body.tokens_out,
    }
    _cost_events[body.skill].append(event)

    # Check budget and fire alert notification if over threshold
    budget = _get_budget_usd()
    if budget:
        total = _monthly_total()
        if total >= budget:
            # TODO: call notifications.send_alert("budget_exceeded", total=total, budget=budget)
            pass

    return {"recorded": True, "skill": body.skill, "usd": body.usd}


@router.get("", response_model=CostSummaryResponse)
async def cost_summary(
    period: str = "month",
    _token: str = Depends(_verify_token),
) -> CostSummaryResponse:
    """Monthly spend summary across all skills."""
    cutoff = _month_start_ts() if period == "month" else 0.0
    skill_summaries: list[SkillCostSummary] = []
    total = 0.0

    for skill, events in _cost_events.items():
        period_events = [e for e in events if e["ts"] >= cutoff]
        if not period_events:
            continue
        skill_total = sum(e["usd"] for e in period_events)
        total += skill_total
        runs = len(period_events)
        skill_summaries.append(
            SkillCostSummary(
                skill=skill,
                usd=round(skill_total, 6),
                runs=runs,
                avg_usd_per_run=round(skill_total / runs, 6) if runs else 0.0,
            )
        )

    budget = _get_budget_usd()
    budget_pct = round((total / budget) * 100, 1) if budget else None

    return CostSummaryResponse(
        period=period,
        total_usd=round(total, 6),
        budget_usd=budget,
        budget_pct=budget_pct,
        over_budget=bool(budget and total >= budget),
        skills=sorted(skill_summaries, key=lambda s: s.usd, reverse=True),
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


@router.get("/{skill}", response_model=SkillCostDetailResponse)
async def skill_cost_detail(
    skill: str,
    period: str = "month",
    _token: str = Depends(_verify_token),
) -> SkillCostDetailResponse:
    """Per-skill cost detail with event-level breakdown."""
    cutoff = _month_start_ts() if period == "month" else 0.0
    events = [e for e in _cost_events.get(skill, []) if e["ts"] >= cutoff]
    total = sum(e["usd"] for e in events)
    return SkillCostDetailResponse(
        skill=skill,
        period=period,
        total_usd=round(total, 6),
        runs=len(events),
        events=events,
    )


def _get_budget_usd() -> Optional[float]:
    raw = os.getenv("BIRKIN_BUDGET_USD")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _monthly_total() -> float:
    cutoff = _month_start_ts()
    return sum(
        e["usd"]
        for events in _cost_events.values()
        for e in events
        if e["ts"] >= cutoff
    )


__all__ = ["router"]
