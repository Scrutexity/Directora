"""LangGraph node that turns receipt_input into the Authority Brief and
the Directora-compatible generation input.

Strict validation (default) protects the whole pipe: a malformed receipt
raises ReceiptValidationError, which this node catches, records as
`receipt_invalid` in the Governed Workflow Ledger, and surfaces as a
structured error state. No best-effort defaulting happens silently.

If `state.receipt_input` is absent, the run is treated as "generic mode"
and the pipeline preserves the legacy topic + brand_kit behaviour.
"""
from __future__ import annotations

from typing import Any

from directora.scrutexity import authority_brief as _ab
from directora.scrutexity.schema import ReceiptValidationError
from directora.telemetry.outcome import record_outcome


def run(state: Any) -> dict:
    receipt = getattr(state, "receipt_input", None)
    if not receipt:
        # Generic mode: pipeline keeps working with topic + brand_kit as before.
        return {
            "authority_brief": None,
            "directora_input": None,
            "mode": "generic",
        }

    clinic_context = getattr(state, "clinic_context", None)
    strict = bool(getattr(state, "strict_receipt", True))

    try:
        brief = _ab.build_authority_brief(receipt, clinic_context, strict=strict)
    except ReceiptValidationError as exc:
        # Structured error path — pipeline does not blow up, but the
        # downstream nodes see mode="error" and route accordingly.
        record_outcome(
            state,
            kind="receipt_invalid",
            reason=str(exc),
            risk_level="high",
            approval_status="blocked: receipt validation failed",
            validation_errors=exc.errors,
        )
        return {
            "authority_brief": None,
            "authority_brief_validation": {
                "ok": False,
                "errors": [str(e) for e in exc.errors],
                "structured_errors": exc.errors,
            },
            "directora_input": None,
            "mode": "error",
            "approval_status": "blocked: receipt validation failed",
            "receipt_validation_error": exc.to_dict(),
        }

    validation = _ab.validate_authority_brief(brief)
    di = _ab.authority_brief_to_directora_input(brief)

    record_outcome(
        state,
        kind="authority_brief_created",
        clinic_name=brief.get("clinic_name"),
        treatment=brief.get("treatment"),
        market=brief.get("market"),
        approval_status="human approval required",
        validation_ok=validation["ok"],
        validation_warnings=len(validation["warnings"]),
    )

    return {
        "authority_brief": brief,
        "authority_brief_validation": validation,
        "directora_input": di,
        "mode": "scrutexity",
        # Pass-through state shortcuts that other nodes read directly.
        "clinic_name": brief.get("clinic_name"),
        "treatment": brief.get("treatment"),
        "market": brief.get("market"),
        "primary_visibility_gap": brief.get("primary_visibility_gap"),
        "competitors_surfacing_more_often": brief.get(
            "competitors_surfacing_more_often", []
        ),
        "first_fix_id_prioritize": brief.get("first_fix_id_prioritize"),
        "claim_risk_notes": brief.get("claim_risk_notes", []),
        "approval_status": "human approval required",
    }
