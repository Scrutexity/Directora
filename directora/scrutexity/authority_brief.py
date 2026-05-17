"""
Scrutexity Authority Brief — the translation layer between an AI
Visibility Receipt and the internal Authority Engine inputs.

Public API:
    build_authority_brief(receipt, clinic_context=None)        -> dict
    validate_authority_brief(brief)                            -> dict
    authority_brief_to_directora_input(brief)                  -> dict

The brief is a plain dict (not a dataclass) so it round-trips cleanly
through JSON and through state.* fields without serialisation drama.
Field names match the canonical Scrutexity shape documented in the
project rules and the public README.
"""
from __future__ import annotations

from typing import Any

from directora.scrutexity import language as _lang
from directora.scrutexity import schema as _schema
from directora.scrutexity.schema import ReceiptValidationError

# Canonical asset slugs that the export module knows how to render.
_VALID_CONTENT_OUTPUTS: tuple[str, ...] = (
    "short_form_script",
    "faq_block",
    "gbp_post",
    "landing_page_section",
    "provider_quote",
    "owner_brief_snippet",
    "provider_brief_snippet",
)

_DEFAULT_TONE = "clinical, premium, trust-first, non-hype"
_DEFAULT_CONTENT_OUTPUTS = (
    "short_form_script",
    "faq_block",
    "gbp_post",
    "landing_page_section",
    "provider_quote",
)

_REQUIRED_KEYS: tuple[str, ...] = (
    "clinic_name",
    "market",
    "treatment",
    "primary_visibility_gap",
)


def _first_present(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _normalise_list(items: Any) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        items = [items]
    return _lang.normalize_iterable(str(x) for x in items)


def build_authority_brief(
    receipt: dict,
    clinic_context: dict | None = None,
    *,
    strict: bool = True,
) -> dict:
    """Convert an AI Visibility Receipt into a Scrutexity Authority Brief.

    With `strict=True` (default), the receipt is validated against
    `AIVisibilityReceipt` first. Malformed receipts raise
    `ReceiptValidationError` — callers (the LangGraph node) should catch
    and record `receipt_invalid` in the Governed Workflow Ledger.

    With `strict=False`, validation failures fall back to best-effort
    parsing of the raw dict (legacy v3.1 behaviour). Use only for
    migration or debugging. The validation report is exposed via
    `validate_authority_brief(brief)` regardless.
    """
    # Validate first — strict mode raises before we touch any field.
    receipt = _schema.validate_receipt(receipt, strict=strict)
    ctx = clinic_context or {}

    clinic_name = _first_present(ctx, "clinic_name", default=None) or _first_present(
        receipt, "clinic_name", "clinic", default="Unspecified Clinic"
    )
    market = _first_present(ctx, "market", default=None) or _first_present(
        receipt, "market", "geo", "location", default="Unspecified Market"
    )
    treatment = _first_present(
        receipt, "treatment", "service", default="Unspecified Treatment"
    )

    visibility_gap = _first_present(
        receipt, "visibility_gap", default="Did not surface in this prompt set"
    )
    primary_gap = _first_present(
        receipt, "primary_visibility_gap", default=visibility_gap
    )

    competitors = _normalise_list(
        receipt.get("competitors_surfacing_more_often")
        or receipt.get("competitors")
        or []
    )

    claim_notes = list(
        receipt.get("claim_risk_notes")
        or [
            "Avoid guaranteed results",
            "Avoid unqualified before/after promises",
            "Avoid implying clinical outcome certainty",
        ]
    )

    content_outputs = list(
        receipt.get("content_outputs_needed") or _DEFAULT_CONTENT_OUTPUTS
    )
    content_outputs = [
        c for c in content_outputs if c in _VALID_CONTENT_OUTPUTS
    ]

    first_fix = _first_present(
        receipt,
        "first_fix_id_prioritize",
        "first_fix",
        default=(
            f"Create provider-led educational content around {treatment} "
            f"with safe expectations and a consult CTA"
        ),
    )

    brief = {
        "clinic_name": clinic_name,
        "market": market,
        "treatment": treatment,
        "visibility_gap": _lang.normalize_language(str(visibility_gap)),
        "primary_visibility_gap": _lang.normalize_language(str(primary_gap)),
        "competitors_surfacing_more_often": competitors,
        "patient_intent": _lang.normalize_language(
            str(receipt.get("patient_intent") or "Treatment research with booking intent")
        ),
        "trust_gap": _lang.normalize_language(
            str(receipt.get("trust_gap") or "Treatment page lacks provider proof and recovery expectations")
        ),
        "booking_friction": _lang.normalize_language(
            str(receipt.get("booking_friction") or "CTA is below the fold or not treatment-specific")
        ),
        "claim_risk_notes": claim_notes,
        "first_fix_id_prioritize": _lang.normalize_language(str(first_fix)),
        "content_outputs_needed": content_outputs or list(_DEFAULT_CONTENT_OUTPUTS),
        "tone": _first_present(ctx, "tone", default=None)
        or receipt.get("tone")
        or _DEFAULT_TONE,
        "approval_required": True,
    }
    return brief


def validate_authority_brief(brief: dict) -> dict:
    """Return a validation report. `ok` is True only when all required
    keys are present and no forbidden language survives in the visible
    fields. Never raises — the caller decides what to do with errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    for key in _REQUIRED_KEYS:
        if not brief.get(key):
            errors.append(f"missing required field: {key}")

    for key in (
        "visibility_gap",
        "primary_visibility_gap",
        "patient_intent",
        "trust_gap",
        "booking_friction",
        "first_fix_id_prioritize",
    ):
        hits = _lang.contains_forbidden(str(brief.get(key, "")))
        if hits:
            warnings.append(
                f"{key} contained forbidden language: {sorted(set(hits))}"
            )

    bad_outputs = [
        c for c in brief.get("content_outputs_needed", [])
        if c not in _VALID_CONTENT_OUTPUTS
    ]
    if bad_outputs:
        errors.append(f"unknown content_outputs_needed: {bad_outputs}")

    if brief.get("approval_required") is not True:
        warnings.append("approval_required must remain True for clinic output")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def authority_brief_to_directora_input(brief: dict) -> dict:
    """Map a validated Authority Brief into the topic + brand kit + compliance
    constraints shape the existing Directora pipeline already understands.

    Mapping:
      treatment + market + Primary Visibility Gap -> topic
      clinic_name + tone + trust_gap              -> brand kit additions
      claim_risk_notes                            -> compliance constraints
      content_outputs_needed                      -> output plan
      first_fix_id_prioritize                     -> creative direction
    """
    treatment = brief.get("treatment", "Unspecified Treatment")
    market = brief.get("market", "Unspecified Market")
    primary_gap = brief.get("primary_visibility_gap", "")

    topic = (
        f"Treatment-level visibility for {treatment} in {market}. "
        f"Primary Visibility Gap: {primary_gap}"
    )

    brand_kit = {
        "name": brief.get("clinic_name", "Unspecified Clinic"),
        "tone": brief.get("tone", _DEFAULT_TONE),
        "voice_notes": [
            "Provider-led, premium-clinical voice",
            f"Trust gap to repair: {brief.get('trust_gap','')}",
            "Avoid hype, avoid SEO-agency phrasing",
        ],
        "market": market,
        "treatment": treatment,
    }

    compliance_constraints = list(brief.get("claim_risk_notes", []))
    # Always reinforce the canonical defaults even if the caller dropped them.
    for default_note in (
        "Avoid guaranteed results",
        "Avoid unsupported clinical claims",
        "Avoid implying treatment suitability for a specific patient",
        "Recommend provider review before publishing",
        "Preserve PHI-minimizing workflows",
    ):
        if default_note not in compliance_constraints:
            compliance_constraints.append(default_note)

    return {
        "mode": "scrutexity",
        "topic": topic,
        "brand_kit": brand_kit,
        "compliance_constraints": compliance_constraints,
        "output_plan": list(brief.get("content_outputs_needed", [])),
        "creative_direction": brief.get("first_fix_id_prioritize", ""),
        "approval_required": brief.get("approval_required", True),
        # Pass-through fields the rest of the pipeline reads from state.
        "clinic_name": brief.get("clinic_name"),
        "treatment": treatment,
        "market": market,
        "primary_visibility_gap": primary_gap,
        "competitors_surfacing_more_often": list(
            brief.get("competitors_surfacing_more_often", [])
        ),
        "first_fix_id_prioritize": brief.get("first_fix_id_prioritize", ""),
        "claim_risk_notes": list(brief.get("claim_risk_notes", [])),
    }
