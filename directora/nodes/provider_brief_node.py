"""LangGraph node that produces the Provider Brief snippet.

Sits in the Brief Path alongside owner_brief_node. The Provider Brief
gives the clinic's provider the claim-risk review checklist, the
selected Authority Review recommendation, and the safe-language rules
they should apply before approving the asset bundle for publication.

v3.4: also persists the canonical Provider Brief JSON + brief_content_hash
into the brief store so the sign-off API can hash and sign the exact
artifact that triggered `provider_brief_ready`. No re-rendering.
"""
from __future__ import annotations

from typing import Any

from directora.api.hashing import hash_brief_dict
from directora.scrutexity import export as _export
from directora.scrutexity.brief_store import (
    BriefRecord,
    BriefStatus,
    get_brief_store,
)
from directora.scrutexity.canonical_json import canonical_dumps
from directora.scrutexity.personas import AUTHORITY_REVIEW_PERSONAS
from directora.telemetry.outcome import record_outcome, summarise


def run(state: Any) -> dict:
    brief = getattr(state, "authority_brief", None)
    if not brief:
        # Generic mode — Provider Brief is a no-op.
        return {"provider_brief": None}

    run_id = getattr(state, "run_id", "unknown") or "unknown"
    ledger_summary = summarise(run_id)
    review_summary = getattr(state, "authority_review_summary", None)

    provider_brief = _export.render_provider_brief(
        brief,
        review_summary=review_summary,
        ledger_summary=ledger_summary,
        personas=AUTHORITY_REVIEW_PERSONAS,
    )

    # Compute the canonical artifact and its hash NOW — at generation
    # time — so the sign-off API never re-renders or re-hashes.
    canonical_json = canonical_dumps(provider_brief)
    brief_content_hash = hash_brief_dict(provider_brief)

    # Persist into the brief store so the API can fetch the same bytes.
    brief_id = getattr(state, "brief_id", None) or run_id
    clinic_id = (
        getattr(state, "clinic_id", None)
        or getattr(state, "clinic_name", None)
        or "unknown"
    )
    provider_id = getattr(state, "provider_id", None) or "unassigned"

    store = get_brief_store()
    existing = store.get(brief_id)
    record = BriefRecord(
        brief_id=brief_id,
        clinic_id=str(clinic_id),
        provider_id=str(provider_id),
        treatment=str(brief.get("treatment") or ""),
        market=str(brief.get("market") or ""),
        status=(existing.status if existing else BriefStatus.PENDING_REVIEW),
        patient_ref=getattr(state, "patient_ref", None),
        encounter_ref=getattr(state, "encounter_ref", None),
        engine_run_id=run_id,
        authority_brief_version=str(getattr(state, "authority_brief_version", "1")),
        provider_brief_version=str(getattr(state, "provider_brief_version", "1")),
        provider_brief_canonical_json=canonical_json,
        brief_content_hash=brief_content_hash,
        lab_summary_flags=dict(getattr(state, "lab_summary_flags", {}) or {}),
        results=list(getattr(state, "results", []) or []),
        claim_risk_items=list(brief.get("claim_risk_notes", []) or []),
    )
    # Preserve signed timestamps and ledger event id on re-emit.
    if existing and existing.status == BriefStatus.SIGNED:
        record.status = BriefStatus.SIGNED
        record.signed_at = existing.signed_at
        record.ledger_event_id = existing.ledger_event_id
    store.put(record)

    record_outcome(
        state,
        kind="provider_brief_ready",
        clinic_name=brief.get("clinic_name"),
        treatment=brief.get("treatment"),
        market=brief.get("market"),
        clinic_id=str(clinic_id),
        provider_id=str(provider_id),
        brief_id=brief_id,
        approval_status=provider_brief.get("human_approval_status"),
        risk_level=(
            (provider_brief.get("selected_recommendation") or {}).get("risk_level")
        ),
        brief_content_hash=brief_content_hash,
        engine_run_id=run_id,
        authority_brief_version=record.authority_brief_version,
        provider_brief_version=record.provider_brief_version,
    )
    return {
        "provider_brief": provider_brief,
        "provider_brief_canonical_json": canonical_json,
        "brief_content_hash": brief_content_hash,
        "brief_id": brief_id,
    }
