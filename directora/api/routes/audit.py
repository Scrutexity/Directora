"""/api/labs/audit route.

Append-only ledger view filtered by brief_id. Read-only. Authenticated.
No PHI in the response — sign-off events carry only IDs, hashes, and
timestamps.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from directora.api.auth import Principal, resolve_principal
from directora.api.schemas import AuditEvent, AuditResponse
from directora.api.storage import get_brief_store
from directora.telemetry.outcome import list_events_for_brief

router = APIRouter(prefix="/api/labs", tags=["audit"])


@router.get("/audit", response_model=AuditResponse)
def audit_for_brief(
    brief_id: str = Query(...),
    principal: Principal = Depends(resolve_principal),
) -> AuditResponse:
    record = get_brief_store().get(brief_id)
    if record is None:
        raise HTTPException(status_code=404, detail="brief_not_found")
    if record.clinic_id != principal.clinic_id:
        raise HTTPException(status_code=403, detail="clinic_mismatch")
    raw_events = list_events_for_brief(brief_id)
    events = []
    for e in raw_events:
        # AuditEvent.extra="allow" preserves all fields.
        events.append(AuditEvent(**{k: v for k, v in e.items() if k != "extra"},
                                 **(e.get("extra") or {})))
    return AuditResponse(brief_id=brief_id, events=events)


__all__ = ["router"]
