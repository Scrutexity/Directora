"""Feature 1 — Siri Shortcuts integration.

POST /api/skills/{name}/trigger
    Accepts a bearer token + optional params dict.
    Returns a run_id the Shortcut can surface as a notification.
    "Hey Siri, run sourcing-intel" → this endpoint → Hermes agent fires.
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from directora.api.secrets import get_secret

router = APIRouter(prefix="/api/skills", tags=["skills"])

_bearer = HTTPBearer(auto_error=True)

KNOWN_SKILLS: dict[str, dict[str, Any]] = {
    "sourcing-intel": {"description": "Run sourcing intelligence sweep"},
    "daily-brief": {"description": "Compile daily briefing"},
    "competitor-monitor": {"description": "Check competitor signals"},
    "governance-check": {"description": "Verify agent integrity"},
}


def _verify_token(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    expected = get_secret("BIRKIN_TOKEN")
    if not expected or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return creds.credentials


class SkillTriggerRequest(BaseModel):
    params: Optional[dict[str, Any]] = None
    source: str = "manual"  # siri | shortcut | manual | schedule


class SkillTriggerResponse(BaseModel):
    skill: str
    status: str  # queued | running | completed | unknown_skill
    run_id: str
    triggered_at: str
    source: str


class SkillListResponse(BaseModel):
    skills: list[str]
    total: int


@router.get("", response_model=SkillListResponse)
async def list_skills(_token: str = Depends(_verify_token)) -> SkillListResponse:
    """Return all registered Hermes skills."""
    names = list(KNOWN_SKILLS.keys())
    return SkillListResponse(skills=names, total=len(names))


@router.post("/{name}/trigger", response_model=SkillTriggerResponse)
async def trigger_skill(
    name: str,
    body: SkillTriggerRequest,
    _token: str = Depends(_verify_token),
) -> SkillTriggerResponse:
    """Trigger a Hermes agent skill by name.

    Siri Shortcut flow:
      1. Shortcut POSTs here with Authorization: Bearer $BIRKIN_TOKEN
      2. Server queues the agent run and returns run_id
      3. Shortcut reads run_id from response → shows notification
    """
    if name not in KNOWN_SKILLS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown skill '{name}'. Known skills: {list(KNOWN_SKILLS)}",
        )

    run_id = f"run_{name}_{int(time.time())}_{secrets.token_hex(4)}"

    # TODO: dispatch to Hermes agent runtime here
    # hermes.dispatch(skill=name, params=body.params, run_id=run_id)

    return SkillTriggerResponse(
        skill=name,
        status="queued",
        run_id=run_id,
        triggered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        source=body.source,
    )


__all__ = ["router"]
