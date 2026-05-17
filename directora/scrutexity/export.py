"""
Scrutexity export layer.

Renders the six Authority Asset types that a clinic owner can publish or
hand to a provider. Each render returns a structured dict so the caller
(graph node, API surface, or owner-brief generator) can wrap it however
it wants — markdown, JSON, or directly into a webpage artifact.

Public API:
    SUPPORTED_ASSETS                      tuple of asset type slugs
    render_asset(asset_type, brief, body) -> dict
    render_bundle(brief, drafted)          -> list[dict]
    render_owner_brief(brief, ledger_summary) -> dict
"""
from __future__ import annotations

from typing import Any, Iterable

from directora.scrutexity import language as _lang

SUPPORTED_ASSETS: tuple[str, ...] = (
    "short_form_script",
    "faq_block",
    "gbp_post",
    "landing_page_section",
    "provider_quote",
    "owner_brief_snippet",
    "provider_brief_snippet",
)

# Human-readable labels for clinic-facing UI / markdown headers.
_LABELS: dict[str, str] = {
    "short_form_script": "Short-form Provider-Led Script",
    "faq_block": "FAQ Block",
    "gbp_post": "Google Business Profile Post",
    "landing_page_section": "Landing Page Section",
    "provider_quote": "Provider Quote",
    "owner_brief_snippet": "Owner Brief Snippet",
    "provider_brief_snippet": "Provider Brief",
}


def _base_metadata(brief: dict) -> dict:
    """Common metadata block stamped onto every clinic-facing export."""
    return {
        "clinic_name": brief.get("clinic_name"),
        "treatment": brief.get("treatment"),
        "market": brief.get("market"),
        "Primary Visibility Gap": brief.get("primary_visibility_gap"),
        "First Fix I'd Prioritize": brief.get("first_fix_id_prioritize"),
        "claim_risk_notes": list(brief.get("claim_risk_notes", [])),
        "approval_required": bool(brief.get("approval_required", True)),
        "disclaimer": _lang.DISCLAIMER,
    }


def _ensure_safe_body(text: str) -> str:
    """Scrub forbidden language and any leaked internal engine names."""
    return _lang.normalize_language(text or "")


def render_asset(
    asset_type: str, brief: dict, body: str | dict | None = None
) -> dict:
    """Render a single asset.

    `body` is the drafted content from the generation node. If `body` is a
    dict, we treat it as a structured payload (e.g. a script with hook +
    beats); if it's a string, we wrap it as markdown.
    """
    if asset_type not in SUPPORTED_ASSETS:
        raise ValueError(
            f"Unknown asset_type {asset_type!r}. "
            f"Supported: {list(SUPPORTED_ASSETS)}"
        )

    safe_body: Any
    if isinstance(body, dict):
        safe_body = {k: _ensure_safe_body(str(v)) if isinstance(v, str) else v
                     for k, v in body.items()}
    else:
        safe_body = _ensure_safe_body(str(body or ""))

    return {
        "asset_type": asset_type,
        "label": _LABELS[asset_type],
        "body": safe_body,
        **_base_metadata(brief),
    }


def render_bundle(brief: dict, drafted: dict[str, Any]) -> list[dict]:
    """Render every asset listed in brief.content_outputs_needed.

    `drafted` is keyed by asset_type and supplies the body for each. If an
    asset is requested but no body is supplied, we still emit an entry with
    an empty body and a flag so the owner brief surfaces the gap.
    """
    bundle: list[dict] = []
    for asset_type in brief.get("content_outputs_needed", []):
        if asset_type not in SUPPORTED_ASSETS:
            continue
        body = drafted.get(asset_type)
        rendered = render_asset(asset_type, brief, body)
        if body is None:
            rendered["body_missing"] = True
        bundle.append(rendered)
    return bundle


def _format_competitor_list(items: Iterable[str]) -> str:
    items = list(items)
    if not items:
        return "—"
    return ", ".join(items)


# ---------- Provider Brief (Brief Path, provider-facing) ----------------


# Baseline checklist items that always apply to medical aesthetics output.
# Receipt-level claim_risk_notes are appended to this baseline so the
# provider sees both the generic governance items and the specific
# concerns flagged for this treatment + market.
_BASELINE_CHECKLIST: tuple[str, ...] = (
    "Does the asset avoid guaranteed-outcome claims?",
    "Does the asset avoid unsupported clinical claims?",
    "Does the asset avoid implying treatment suitability for a specific patient?",
    "Does the asset avoid personalized medical advice?",
    "Does the asset preserve PHI-minimizing workflows?",
    "Does the asset recommend provider review before publishing?",
    "Is the human approval status surfaced for the clinic owner?",
)


def _normalise_note_to_checklist_item(note: str) -> str:
    """Turn an 'Avoid X' note into a 'Have we avoided X?' checklist item."""
    text = (note or "").strip()
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("avoid "):
        rest = text[len("avoid "):].rstrip(". ")
        return f"Have we avoided {rest}?"
    if lower.startswith("recommend "):
        return f"Have we {text[0].lower()}{text[1:].rstrip('. ')}?"
    return text if text.endswith("?") else f"{text.rstrip('.')}?"


def _build_claim_risk_checklist(brief: dict) -> list[str]:
    items = list(_BASELINE_CHECKLIST)
    for note in brief.get("claim_risk_notes", []) or []:
        derived = _normalise_note_to_checklist_item(str(note))
        if derived and derived not in items:
            items.append(derived)
    return items


def _collect_safe_language(personas: list | None) -> list[str]:
    """Pull safe-language rules from the Authority Review persona set.

    `personas` is the iterable of Persona dataclass instances. If not
    supplied, the function returns a small canonical default so callers
    that do not import the personas module still get a non-empty list.
    """
    out: list[str] = []
    if personas:
        for p in personas:
            rules = getattr(p, "safe_language_rules", None) or []
            for r in rules:
                if r and r not in out:
                    out.append(str(r))
    if not out:
        out = [
            "Prefer 'supported (with provider review)' over 'guaranteed'.",
            "Use 'PHI-minimizing workflows' rather than HIPAA marketing language.",
            "Always recommend provider review before publishing.",
            "Use a treatment-specific consult CTA (e.g. 'Book a Morpheus8 consult').",
        ]
    return out


def _select_recommendation(review_summary: list | None) -> dict | None:
    """Find the marked Selected Recommendation, or fall back to the
    highest-risk turn so the provider always sees a starting point."""
    if not review_summary:
        return None
    selected = next(
        (t for t in review_summary if t.get("selected_recommendation")
         or t.get("is_winner")),
        None,
    )
    if selected:
        return selected
    # Fallback: pick the highest-risk turn; ties broken by score.
    risk_rank = {"high": 3, "medium": 2, "low": 1}
    return max(
        review_summary,
        key=lambda t: (
            risk_rank.get(str(t.get("risk_level", "low")).lower(), 0),
            t.get("score") or 0.0,
        ),
        default=None,
    )


def _provider_facing_summary(brief: dict, selected: dict | None) -> str:
    """Short prose paragraph for the provider doing the claim-risk review."""
    lines = [
        f"Clinic: {brief.get('clinic_name')}. "
        f"Treatment: {brief.get('treatment')}. "
        f"Market: {brief.get('market')}.",
        f"Primary Visibility Gap: {brief.get('primary_visibility_gap')}",
        f"First Fix I'd Prioritize: {brief.get('first_fix_id_prioritize')}",
    ]
    if selected:
        lines.append(
            f"Lead concern from Authority Review: {selected.get('reviewer_role')} — "
            f"{selected.get('finding','').strip()} "
            f"Recommended fix: {selected.get('recommended_fix','').strip()}"
        )
    lines.append(
        "Please verify each item in the claim-risk review checklist before approving."
    )
    return _lang.normalize_language(" ".join(lines))


def render_provider_brief(
    brief: dict,
    review_summary: list | None = None,
    ledger_summary: dict | None = None,
    personas: list | None = None,
) -> dict:
    """Render the Provider Brief snippet (Brief Path, provider-facing).

    The Provider Brief is what a clinic's provider sees when they are
    asked to do the claim-risk review before an asset bundle is
    published. It includes:

    - clinic_name, treatment, market
    - Primary Visibility Gap, First Fix I'd Prioritize
    - claim-risk review checklist (baseline + receipt-specific items)
    - selected recommendation from the Authority Review Summary
    - suggested safe language (from persona rules)
    - human approval status
    - provider-facing prose summary
    - disclaimer
    - export packet metadata
    """
    ledger_summary = ledger_summary or {}
    selected = _select_recommendation(review_summary)
    checklist = _build_claim_risk_checklist(brief)
    safe_language = _collect_safe_language(personas)

    counts = {
        "assets_drafted": ledger_summary.get("by_kind", {}).get("asset_drafted", 0),
        "claim_risk_flagged": ledger_summary.get("claim_risk_count", 0),
        "human_approval_required": ledger_summary.get(
            "human_approval_required_count", 0
        ),
        "render_fallback": ledger_summary.get("render_fallback_count", 0),
    }

    return {
        "asset_type": "provider_brief_snippet",
        "label": _LABELS["provider_brief_snippet"],
        "headline": (
            f"Provider Brief: claim-risk review for "
            f"{brief.get('treatment')} at {brief.get('clinic_name')}"
        ),
        "provider_facing_summary": _provider_facing_summary(brief, selected),
        "claim_risk_review_checklist": checklist,
        "suggested_safe_language": safe_language,
        "selected_recommendation": selected,
        "approval_required": bool(brief.get("approval_required", True)),
        "human_approval_status": "human approval required"
        if brief.get("approval_required", True)
        else "approved",
        "ledger_counts": counts,
        "next_actions": [
            "Walk the claim-risk review checklist for each drafted asset.",
            "Apply suggested safe language to any flagged line items.",
            "Confirm the selected Authority Review recommendation is addressed.",
            "Mark human approval status and return the packet to the clinic owner.",
        ],
        **_base_metadata(brief),
    }


# ---------- Owner Brief (Brief Path, owner-facing) ----------------------


def render_owner_brief(brief: dict, ledger_summary: dict | None = None) -> dict:
    """Produce the Weekly Owner Brief snippet payload.

    The owner brief is part of the Brief Path, not the Authority Asset
    Path — it summarises what was generated, what risks were flagged,
    and what still needs human approval. Returns a structured dict the
    caller can render to markdown/HTML or push into the Brief workflow.
    """
    ledger_summary = ledger_summary or {}
    competitors = _format_competitor_list(
        brief.get("competitors_surfacing_more_often", [])
    )

    summary_lines = [
        f"Clinic: {brief.get('clinic_name')}",
        f"Treatment: {brief.get('treatment')}",
        f"Market: {brief.get('market')}",
        f"Primary Visibility Gap: {brief.get('primary_visibility_gap')}",
        f"Competitors Surfacing More Often: {competitors}",
        f"First Fix I'd Prioritize: {brief.get('first_fix_id_prioritize')}",
    ]

    # Pull headline counts from the Governed Workflow Ledger summary.
    counts = {
        "assets_drafted": ledger_summary.get("by_kind", {}).get("asset_drafted", 0),
        "claim_risk_flagged": ledger_summary.get("claim_risk_count", 0),
        "human_approval_required": ledger_summary.get(
            "human_approval_required_count", 0
        ),
        "render_fallback": ledger_summary.get("render_fallback_count", 0),
        "treatments_processed": ledger_summary.get("treatments_processed", 0),
    }

    return {
        "asset_type": "owner_brief_snippet",
        "label": _LABELS["owner_brief_snippet"],
        "summary": "\n".join(summary_lines),
        "claim_risk_notes": list(brief.get("claim_risk_notes", [])),
        "approval_required": bool(brief.get("approval_required", True)),
        "human_approval_status": "human approval required"
        if brief.get("approval_required", True)
        else "approved",
        "ledger_counts": counts,
        "next_actions": [
            "Run claim-risk review with the named provider",
            "Confirm Primary Visibility Gap with the AI Visibility Receipt",
            "Approve or revise the drafted Authority Asset bundle",
        ],
        **_base_metadata(brief),
    }
