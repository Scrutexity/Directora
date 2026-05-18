"""Feature 3 — Shortcuts automation / scheduled triggers.

POST /api/schedules    create a named trigger (cron or geofence label)
GET  /api/schedules    list all active schedules
DELETE /api/schedules/{id}  remove a schedule

The server fires the linked skill at the scheduled time.
Examples:
  daily-brief     → cron "0 7 * * *"   (7 AM every day)
  competitor-monitor → geofence "office" (fires on arrive/depart)
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from directora.api.secrets import get_secret

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_bearer = HTTPBearer(auto_error=True)

_schedules: dict[str, dict[str, Any]] = {}


def _verify_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    expected = get_secret("BIRKIN_TOKEN")
    if not expected or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return creds.credentials


class ScheduleCreate(BaseModel):
    skill: str
    trigger_type: Literal["cron", "geofence"] = "cron"
    cron: Optional[str] = None        # e.g. "0 7 * * *"
    geofence: Optional[str] = None    # e.g. "office", "home"
    geofence_event: Literal["arrive", "depart", "both"] = "arrive"
    params: Optional[dict[str, Any]] = None
    enabled: bool = True


class ScheduleResponse(BaseModel):
    id: str
    skill: str
    trigger_type: str
    cron: Optional[str]
    geofence: Optional[str]
    geofence_event: str
    params: Optional[dict[str, Any]]
    enabled: bool
    created_at: str


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleResponse]
    total: int


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreate,
    _token: str = Depends(_verify_token),
) -> ScheduleResponse:
    """Create a scheduled or geofence-triggered agent run."""
    if body.trigger_type == "cron" and not body.cron:
        raise HTTPException(status_code=422, detail="cron expression required for trigger_type='cron'")
    if body.trigger_type == "geofence" and not body.geofence:
        raise HTTPException(status_code=422, detail="geofence name required for trigger_type='geofence'")

    schedule_id = f"{body.skill}-{secrets.token_hex(4)}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    record: dict[str, Any] = {
        "id": schedule_id,
        "skill": body.skill,
        "trigger_type": body.trigger_type,
        "cron": body.cron,
        "geofence": body.geofence,
        "geofence_event": body.geofence_event,
        "params": body.params,
        "enabled": body.enabled,
        "created_at": now,
    }
    _schedules[schedule_id] = record

    # TODO: register with APScheduler or system cron
    # scheduler.add_job(trigger_skill, CronTrigger.from_crontab(body.cron), ...)

    return ScheduleResponse(**record)


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(_token: str = Depends(_verify_token)) -> ScheduleListResponse:
    items = [ScheduleResponse(**v) for v in _schedules.values()]
    return ScheduleListResponse(schedules=items, total=len(items))


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: str,
    _token: str = Depends(_verify_token),
) -> None:
    if schedule_id not in _schedules:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    del _schedules[schedule_id]
    # TODO: remove from APScheduler


__all__ = ["router"]
