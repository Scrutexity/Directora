"""/api/brief/* routes.

GET  /api/brief/pending     return pending briefs awaiting sign-off
POST /api/brief/sign        provider signs a brief (idempotent, hash-bound)
GET  /api/brief/provider    canonical Provider Brief snippet that backs the hash

No PHI in responses. No ledger writes on GET.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from directora.api.auth import Principal, resolve_principal
from directora.api.hashing import (
    compute_binding_hash,
    compute_signature_value_hash,
    request_hash,
)
from directora.scrutexity.canonical_json import canonical_dumps
from directora.api.idempotency import (
    IdempotencyOutcome,
    get_idempotency_store,
)
from directora.api.metrics import (
    BRIEF_SIGN_RESULTS,
    brief_sign_total,
    briefs_pending,
    briefs_signed,
    idempotency_replay_total,
    ledger_append_fail_total,
    sqlite_busy_total,
)
from directora.api.schemas import (
    AuditEvent,
    ClaimRiskItem,
    LabSummaryFlags,
    PendingBriefEngineOutputs,
    PendingBriefEntry,
    PendingBriefLinks,
    PendingBriefResponse,
    ProviderBriefSnippetResponse,
    ResultHighlight,
    SignBriefRequest,
    SignBriefResponse,
)
from directora.api.storage import BriefRecord, BriefStatus, get_brief_store
from directora.scrutexity import language as _lang
from directora.scrutexity.canonical_json import canonical_dumps
from directora.telemetry.outcome import record_outcome

router = APIRouter(prefix="/api/brief", tags=["brief"])


# ---------- helpers ------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _scrub_for_provider_facing(text: str) -> str:
    """Final-pass safety: scrub forbidden language + internal tokens. The
    drift-guard tests assert no internal tokens reach this response."""
    return _lang.normalize_language(text or "")


def _scrub_dict(d: dict) -> dict:
    """Walk a dict and scrub every string value; preserve structure."""
    if not isinstance(d, dict):
        return d
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = _scrub_for_provider_facing(v)
        elif isinstance(v, list):
            out[k] = [
                _scrub_for_provider_facing(x) if isinstance(x, str)
                else _scrub_dict(x) if isinstance(x, dict)
                else x
                for x in v
            ]
        elif isinstance(v, dict):
            out[k] = _scrub_dict(v)
        else:
            out[k] = v
    return out


def _assert_no_phi(payload: dict) -> None:
    """Reject any response carrying PHI-suggestive field names.

    We ban specific PHI identifiers — `patient_name`, `first_name`,
    `last_name`, `full_name`, `dob`, `date_of_birth`, `birth_date`,
    `birthdate`, `ssn`, `social_security`, any `email*`, any `phone*`
    (except `phone_country_code` which is non-identifying alone — not
    used here), any `address*`, `postal_code`, `zip_code`, plus
    well-known patient-identifier slugs.

    Field names like `clinic_name`, `results[*].name` (a lab test name),
    or `reviewer_role` are explicitly NOT PHI and remain allowed.
    """
    BANNED_EXACT = {
        "patient_name", "first_name", "last_name", "full_name",
        "given_name", "surname", "fullname",
        "dob", "date_of_birth", "birth_date", "birthdate", "birthday",
        "ssn", "social_security", "social_security_number",
        "phone_number", "mobile", "cell",
        "street", "postal_code", "zip_code", "zip",
    }
    BANNED_PREFIXES = ("email", "phone", "address")

    def walk(obj):
        if isinstance(obj, dict):
            for k in obj.keys():
                lk = str(k).lower()
                if lk in BANNED_EXACT:
                    raise AssertionError(
                        f"PHI guard: field '{k}' is not allowed"
                    )
                if any(lk == p or lk.startswith(p + "_") for p in BANNED_PREFIXES):
                    raise AssertionError(
                        f"PHI guard: field '{k}' looks like PHI"
                    )
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)


def _build_links(brief_id: str) -> PendingBriefLinks:
    return PendingBriefLinks(
        audit=f"/api/labs/audit?brief_id={brief_id}",
        detail=f"/api/brief/provider?brief_id={brief_id}",
        provider=f"/api/brief/provider?brief_id={brief_id}",
    )


def _engine_outputs_for(record: BriefRecord) -> PendingBriefEngineOutputs:
    """Surface a small preview of the provider brief snippet — never the
    full canonical JSON here. The full thing lives at /api/brief/provider."""
    snippet_preview: dict = {}
    if record.provider_brief_canonical_json:
        try:
            full = json.loads(record.provider_brief_canonical_json)
        except json.JSONDecodeError:
            full = {}
        snippet_preview = {
            "headline": _scrub_for_provider_facing(full.get("headline", "")),
            "human_approval_status": full.get("human_approval_status", ""),
            "approval_required": bool(full.get("approval_required", True)),
            "selected_recommendation_reviewer": (
                (full.get("selected_recommendation") or {}).get("reviewer_role")
            ),
            "claim_risk_review_checklist_count": len(
                full.get("claim_risk_review_checklist", []) or []
            ),
        }
    return PendingBriefEngineOutputs(
        provider_brief_preview=snippet_preview,
        claim_risk={"items": list(record.claim_risk_items or [])},
    )


def _to_pending_entry(record: BriefRecord) -> PendingBriefEntry:
    return PendingBriefEntry(
        brief_id=record.brief_id,
        provider_id=record.provider_id,
        clinic_id=record.clinic_id,
        status=record.status,  # type: ignore[arg-type]
        created_at=record.created_at,
        updated_at=record.updated_at,
        patient_ref=record.patient_ref,
        encounter_ref=record.encounter_ref,
        treatment=record.treatment,
        market=record.market,
        lab_summary=LabSummaryFlags(**record.lab_summary_flags)
        if record.lab_summary_flags
        else LabSummaryFlags(),
        results=[ResultHighlight(**r) if isinstance(r, dict) else r
                 for r in record.results],
        engine_outputs=_engine_outputs_for(record),
        links=_build_links(record.brief_id),
    )


# ---------- GET /api/brief/pending ---------------------------------------


@router.get("/pending", response_model=PendingBriefResponse)
def list_pending(
    request: Request,
    provider_id: Optional[str] = Query(default=None),
    status: str = Query(default="pending"),
    limit: int = Query(default=25, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    principal: Principal = Depends(resolve_principal),
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-ID"),
) -> PendingBriefResponse:
    if status != "pending":
        raise HTTPException(status_code=400, detail="only_pending_supported")
    target_provider = provider_id or principal.provider_id
    if target_provider != principal.provider_id and not principal.has_role("medical_director"):
        raise HTTPException(status_code=403, detail="cross_provider_listing_denied")
    records, next_cursor = get_brief_store().list_pending(
        clinic_id=principal.clinic_id,
        provider_id=target_provider,
        limit=limit,
        cursor=cursor,
    )
    response = PendingBriefResponse(
        items=[_to_pending_entry(r) for r in records],
        next_cursor=next_cursor,
    )
    _assert_no_phi(response.model_dump())
    # Sample the pending gauge here. We use the entries in the response
    # rather than a separate count(*) so the gauge reflects what callers
    # actually see.
    briefs_pending.set(float(len(response.items)))
    return response


# ---------- GET /api/brief/provider --------------------------------------


@router.get("/provider", response_model=ProviderBriefSnippetResponse)
def get_provider_brief(
    brief_id: str = Query(...),
    principal: Principal = Depends(resolve_principal),
) -> ProviderBriefSnippetResponse:
    record = get_brief_store().get(brief_id)
    if record is None:
        raise HTTPException(status_code=404, detail="brief_not_found")
    if record.clinic_id != principal.clinic_id:
        raise HTTPException(status_code=403, detail="clinic_mismatch")
    if not record.provider_brief_canonical_json or not record.brief_content_hash:
        raise HTTPException(
            status_code=409, detail="provider_brief_not_generated"
        )
    try:
        snippet = json.loads(record.provider_brief_canonical_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="brief_corrupt") from exc
    # Scrub once more for defence in depth. The drift guard tests assert
    # that this scrub is a no-op against well-formed snippets.
    scrubbed = _scrub_dict(snippet)
    payload = ProviderBriefSnippetResponse(
        asset_type="provider_brief_snippet",
        brief_content_hash=record.brief_content_hash,
        canonical_json=record.provider_brief_canonical_json,
        snippet=scrubbed,
    )
    _assert_no_phi(payload.model_dump())
    return payload


# ---------- POST /api/brief/sign -----------------------------------------


def _error(
    status_code: int,
    code: str,
    *,
    detail: Optional[str] = None,
    ledger_event_id: Optional[str] = None,
) -> JSONResponse:
    body = {"error": code}
    if detail:
        body["detail"] = detail
    if ledger_event_id:
        body["ledger_event_id"] = ledger_event_id
    return JSONResponse(status_code=status_code, content=body)


def _provider_is_authorised(principal: Principal, record: BriefRecord) -> bool:
    if record.provider_id == principal.provider_id:
        return True
    if principal.has_role("medical_director"):
        return True
    return False


def _record_signed_event(
    *,
    state_shim,
    record: BriefRecord,
    brief_content_hash: str,
    signature_value_hash: str,
    binding_hash: str,
    signed_at_iso: str,
    request_id: Optional[str],
    idempotency_key: str,
) -> Optional[str]:
    return record_outcome(
        state_shim,
        kind="provider_brief_signed",
        clinic_id=record.clinic_id,
        provider_id=record.provider_id,
        brief_id=record.brief_id,
        treatment=record.treatment,
        market=record.market,
        approval_status="signed",
        engine_run_id=record.engine_run_id,
        authority_brief_version=record.authority_brief_version,
        provider_brief_version=record.provider_brief_version,
        signature_method=state_shim.signature_method,
        signature_value_hash=signature_value_hash,
        binding_hash=binding_hash,
        brief_content_hash=brief_content_hash,
        signed_at=signed_at_iso,
        correlation_request_id=request_id,
        correlation_idempotency_key=idempotency_key,
        patient_ref=record.patient_ref,
        encounter_ref=record.encounter_ref,
    )


class _LedgerStateShim:
    """Minimal object satisfying record_outcome's getattr access."""
    def __init__(self, *, run_id: str, signature_method: str):
        self.run_id = run_id
        self.signature_method = signature_method
        self.telemetry = {"events": []}


# Map internal sign-outcome codes to the canonical result label set
# exposed by brief_sign_total{result}. Anything not in this map is
# bucketed into engine_or_ledger_failure so dashboards never see
# unexpected labels.
_OUTCOME_TO_RESULT_LABEL = {
    "signed": "signed",
    "already_signed": "already_signed",
    "idempotency_conflict": "idempotency_conflict",
    "invalid_status": "invalid_status",
    "stale_engine_context": "invalid_status",
    "engine_or_ledger_failure": "engine_or_ledger_failure",
    "invalid_signature": "invalid_status",
    # The following are auth / discovery failures rather than sign
    # outcomes; we still increment the counter so on-call has the full
    # picture and they bucket into engine_or_ledger_failure (the catch-all).
    "brief_not_found": "engine_or_ledger_failure",
    "clinic_mismatch": "engine_or_ledger_failure",
    "permission_denied": "engine_or_ledger_failure",
    "missing_idempotency_key": "engine_or_ledger_failure",
}


def _sign_outcome(outcome: str) -> None:
    """Increment brief_sign_total with the canonical result label."""
    try:
        label = _OUTCOME_TO_RESULT_LABEL.get(outcome, "engine_or_ledger_failure")
        if label not in BRIEF_SIGN_RESULTS:  # belt + braces
            label = "engine_or_ledger_failure"
        brief_sign_total.labels(result=label).inc()
    except Exception:  # pragma: no cover
        pass


@router.post("/sign")
def sign_brief(
    payload: SignBriefRequest,
    request: Request,
    principal: Principal = Depends(resolve_principal),
    x_request_id: Optional[str] = Header(default=None, alias="X-Request-ID"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # Latency is captured by the HTTP-level observability metric — no
    # per-route timer needed here.
    return _sign_brief_inner(
        payload, request, principal, x_request_id, idempotency_key,
    )


def _sign_brief_inner(
    payload, request, principal, x_request_id, idempotency_key,
):
    if not idempotency_key:
        _sign_outcome("missing_idempotency_key")
        return _error(400, "missing_idempotency_key")

    store = get_brief_store()
    record = store.get(payload.brief_id)
    if record is None:
        _sign_outcome("brief_not_found")
        return _error(404, "brief_not_found")
    if record.clinic_id != principal.clinic_id:
        _sign_outcome("clinic_mismatch")
        return _error(403, "clinic_mismatch")
    if not _provider_is_authorised(principal, record):
        _sign_outcome("permission_denied")
        return _error(403, "permission_denied")

    body_hash = request_hash(payload.model_dump())
    idem_store = get_idempotency_store()
    # Backpressure: SQLite busy → 503 + Retry-After, not 500.
    try:
        idem_result = idem_store.begin(
            clinic_id=principal.clinic_id,
            provider_id=principal.provider_id,
            brief_id=payload.brief_id,
            route="POST /api/brief/sign",
            idempotency_key=idempotency_key,
            request_hash=body_hash,
        )
    except Exception as exc:
        # Treat any IdempotencyStoreBusy (or generic OperationalError) as
        # transient and tell the client to retry with the SAME key.
        from directora.api.idempotency_store import IdempotencyStoreBusy
        if isinstance(exc, IdempotencyStoreBusy) or "database is locked" in str(exc):
            sqlite_busy_total.inc()
            _sign_outcome("db_busy")
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "1"},
                content={"error": "idempotency_store_busy",
                         "detail": "Retry with the same Idempotency-Key."},
            )
        raise

    if idem_result.outcome == IdempotencyOutcome.REPLAY:
        # Byte-identical replay. Return the canonical bytes verbatim
        # (NOT via JSONResponse — that would re-serialise with FastAPI's
        # encoder and could drift from the original sign-path bytes).
        # The original sign path canonicalises before returning AND
        # before storing, so the two byte streams are equal at the wire.
        idempotency_replay_total.inc()
        _sign_outcome("signed")
        return Response(
            content=canonical_dumps(idem_result.stored_response),
            status_code=200,
            headers={"X-Idempotency-Replayed": "true"},
            media_type="application/json",
        )
    if idem_result.outcome == IdempotencyOutcome.CONFLICT:
        _sign_outcome("idempotency_conflict")
        return _error(409, "idempotency_conflict")

    if record.status == BriefStatus.SIGNED:
        _sign_outcome("already_signed")
        return _error(
            409, "already_signed",
            ledger_event_id=record.ledger_event_id,
        )
    if record.status != BriefStatus.PENDING_REVIEW:
        _sign_outcome("invalid_status")
        return _error(409, "invalid_status",
                      detail=f"status={record.status}")

    # Stale-engine-context check.
    if (
        payload.engine_run_id is not None
        and payload.engine_run_id != record.engine_run_id
    ) or (
        payload.authority_brief_version is not None
        and payload.authority_brief_version != record.authority_brief_version
    ) or (
        payload.provider_brief_version is not None
        and payload.provider_brief_version != record.provider_brief_version
    ):
        _sign_outcome("stale_engine_context")
        return _error(409, "invalid_status", detail="stale_engine_context")

    # Validate signature value bounds — pydantic already enforces length.
    if not payload.signature.value.strip():
        _sign_outcome("invalid_signature")
        return _error(422, "invalid_signature")

    brief_content_hash = record.brief_content_hash or ""
    if not brief_content_hash:
        ledger_append_fail_total.inc()
        _sign_outcome("ledger_failure")
        return _error(500, "engine_or_ledger_failure",
                      detail="brief_content_hash missing")

    signature_value_hash = compute_signature_value_hash(payload.signature.value)
    server_signed_at = _now_iso()
    try:
        binding_hash = compute_binding_hash(
            brief_content_hash=brief_content_hash,
            signature_value_hash=signature_value_hash,
            engine_run_id=record.engine_run_id,
            authority_brief_version=record.authority_brief_version,
            provider_brief_version=record.provider_brief_version,
            clinic_id=record.clinic_id,
            provider_id=record.provider_id,
            signed_at=server_signed_at,
        )
    except Exception:  # MissingClinicSigningSecret or any HMAC failure
        ledger_append_fail_total.inc()
        _sign_outcome("ledger_failure")
        return _error(500, "engine_or_ledger_failure",
                      detail="signing_secret_unavailable")

    shim = _LedgerStateShim(
        run_id=record.engine_run_id or "unknown",
        signature_method=payload.signature.method,
    )
    ledger_event_id = _record_signed_event(
        state_shim=shim,
        record=record,
        brief_content_hash=brief_content_hash,
        signature_value_hash=signature_value_hash,
        binding_hash=binding_hash,
        signed_at_iso=server_signed_at,
        request_id=x_request_id,
        idempotency_key=idempotency_key,
    )
    if not ledger_event_id:
        ledger_append_fail_total.inc()
        _sign_outcome("ledger_failure")
        return _error(500, "engine_or_ledger_failure", detail="ledger_append_failed")

    # Lazy import keeps brief.py independent of any specific backend.
    try:
        from directora.scrutexity.brief_store_sqlite import ConcurrentSignError
    except Exception:  # pragma: no cover
        class ConcurrentSignError(Exception):  # type: ignore[no-redef]
            pass

    try:
        store.mark_signed(
            record.brief_id,
            signed_at=time.time(),
            ledger_event_id=ledger_event_id,
        )
    except ConcurrentSignError:
        # Another writer beat us to it. Append a neutral finalize-failure
        # note (NOT a "rollback") so audit history records what
        # happened without implying a compensation. The original
        # `provider_brief_signed` event remains valid; the brief was
        # signed by the winner.
        record_outcome(
            shim,
            kind="provider_brief_finalize_failed",
            clinic_id=record.clinic_id,
            provider_id=record.provider_id,
            brief_id=record.brief_id,
            reason="lost_concurrent_sign_race",
            risk_level="medium",
            preceded_by=ledger_event_id,
        )
        fresh = store.get(record.brief_id)
        _sign_outcome("already_signed")
        return _error(
            409, "already_signed",
            ledger_event_id=(fresh.ledger_event_id if fresh else None),
        )
    except Exception:
        # Neutral finalize-failure note — never a "rollback". The
        # ledger records that finalize failed; nothing about that
        # event implies the original signed event is invalid.
        record_outcome(
            shim,
            kind="provider_brief_finalize_failed",
            clinic_id=record.clinic_id,
            provider_id=record.provider_id,
            brief_id=record.brief_id,
            reason="mark_signed_failed",
            risk_level="medium",
            preceded_by=ledger_event_id,
        )
        ledger_append_fail_total.inc()
        _sign_outcome("engine_or_ledger_failure")
        return _error(500, "engine_or_ledger_failure",
                      detail="brief_status_update_failed")

    response_body = SignBriefResponse(
        ledger_event_id=ledger_event_id,
        signed_at=server_signed_at,
        brief_content_hash=brief_content_hash,
        binding_hash=binding_hash,
        next_actions={
            "export": f"/api/brief/provider?brief_id={record.brief_id}",
            "audit": f"/api/labs/audit?brief_id={record.brief_id}",
        },
    ).model_dump()

    idem_store.commit(
        clinic_id=principal.clinic_id,
        provider_id=principal.provider_id,
        brief_id=payload.brief_id,
        route="POST /api/brief/sign",
        idempotency_key=idempotency_key,
        request_hash=body_hash,
        response=response_body,
    )
    _sign_outcome("signed")
    briefs_signed.inc()
    # Return canonical bytes — same shape every replay sees.
    # JSONResponse would re-serialise with pydantic field order; the
    # idempotency store's stored_response is canonical (sorted keys),
    # so the original AND the replay both flow through canonical_dumps
    # for true byte-identical replay at the wire.
    return Response(
        content=canonical_dumps(response_body),
        status_code=200,
        media_type="application/json",
    )


__all__ = ["router"]
