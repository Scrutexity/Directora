"""Pydantic v2 models for the Brief API.

Response models keep PHI-minimising IDs only — `patient_ref` and
`encounter_ref`. No names (other than `clinic_name`), DOBs, contact
details, or free-form patient text.
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Pending listing ----------------------------------------------


class LabSummaryFlags(BaseModel):
    critical_count: int = 0
    abnormal_count: int = 0
    claim_risk_flagged: int = 0


class ResultHighlight(BaseModel):
    name: str
    value: Optional[str] = None
    flag: Optional[str] = None
    reference_range: Optional[str] = None


class ClaimRiskItem(BaseModel):
    severity: Literal["low", "medium", "high"] = "medium"
    note: str


class PendingBriefLinks(BaseModel):
    audit: str
    detail: str
    provider: str


class PendingBriefEngineOutputs(BaseModel):
    provider_brief_preview: dict
    claim_risk: dict


class PendingBriefEntry(BaseModel):
    brief_id: str
    provider_id: str
    clinic_id: str
    status: Literal["pending_review", "drafted", "reviewed", "signed"]
    created_at: float
    updated_at: float
    patient_ref: Optional[str] = None
    encounter_ref: Optional[str] = None
    treatment: str
    market: str
    lab_summary: LabSummaryFlags
    results: List[ResultHighlight] = Field(default_factory=list)
    engine_outputs: PendingBriefEngineOutputs
    links: PendingBriefLinks


class PendingBriefResponse(BaseModel):
    items: List[PendingBriefEntry]
    next_cursor: Optional[str] = None


# ---------- Sign request / response --------------------------------------


class SignatureBlock(BaseModel):
    method: Literal["typed", "drawn", "biometric"] = "typed"
    value: str = Field(min_length=1, max_length=512)
    signed_at: str  # ISO 8601 UTC


class ClientBlock(BaseModel):
    app: str
    version: str
    session_id: Optional[str] = None


class SignBriefRequest(BaseModel):
    brief_id: str
    provider_id: str
    signature: SignatureBlock
    client: ClientBlock
    # Optional engine-context echo so the API can detect stale signings
    # client-side. Server still treats stored values as truth.
    engine_run_id: Optional[str] = None
    authority_brief_version: Optional[str] = None
    provider_brief_version: Optional[str] = None


class SignBriefResponse(BaseModel):
    status: Literal["signed"] = "signed"
    ledger_event_id: str
    signed_at: str
    brief_content_hash: str
    binding_hash: str
    next_actions: dict


# ---------- Audit --------------------------------------------------------


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_id: str
    kind: str
    ts: float
    brief_id: Optional[str] = None
    clinic_id: Optional[str] = None
    provider_id: Optional[str] = None
    approval_status: Optional[str] = None
    risk_level: Optional[str] = None


class AuditResponse(BaseModel):
    brief_id: str
    events: List[AuditEvent]


# ---------- Provider snippet --------------------------------------------


class ProviderBriefSnippetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    asset_type: Literal["provider_brief_snippet"]
    brief_content_hash: str
    canonical_json: str  # the exact bytes (UTF-8) backing brief_content_hash
    snippet: dict


# ---------- Error envelope ----------------------------------------------


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    ledger_event_id: Optional[str] = None
    request_id: Optional[str] = None  # injected by observability middleware


# ---------- Reserved (v4.0) Treatment Plan stubs ------------------------
#
# These models are defined so the namespace exists in code but are NOT
# wired to any router. /api/treatment-plan/* paths return 404. Tests
# assert that no Treatment Plan event has been emitted.


class TreatmentPlanResponse(BaseModel):
    """Reserved for v4.0. Do not wire to routes."""
    model_config = ConfigDict(extra="allow")
    asset_type: Literal["treatment_plan_snippet"] = "treatment_plan_snippet"
    treatment_plan_id: Optional[str] = None


class TreatmentPlanSignRequest(BaseModel):
    """Reserved for v4.0. Do not wire to routes."""
    treatment_plan_id: str
    provider_id: str
    signature: SignatureBlock
    client: ClientBlock


class TreatmentPlanSignResponse(BaseModel):
    """Reserved for v4.0. Do not wire to routes."""
    status: Literal["signed"] = "signed"
    ledger_event_id: str
    signed_at: str
    treatment_plan_content_hash: str
    binding_hash: str


__all__ = [
    "LabSummaryFlags",
    "ResultHighlight",
    "ClaimRiskItem",
    "PendingBriefLinks",
    "PendingBriefEngineOutputs",
    "PendingBriefEntry",
    "PendingBriefResponse",
    "SignatureBlock",
    "ClientBlock",
    "SignBriefRequest",
    "SignBriefResponse",
    "AuditEvent",
    "AuditResponse",
    "ProviderBriefSnippetResponse",
    "ErrorResponse",
    # Reserved v4.0:
    "TreatmentPlanResponse",
    "TreatmentPlanSignRequest",
    "TreatmentPlanSignResponse",
]
