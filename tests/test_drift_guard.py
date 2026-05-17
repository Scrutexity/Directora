"""Drift guard tests — provider-facing output must never expose internal tokens."""
from __future__ import annotations

import json

import pytest

from directora.scrutexity import authority_brief as ab
from directora.scrutexity import export
from directora.scrutexity import language as lang
from directora.scrutexity.personas import AUTHORITY_REVIEW_PERSONAS


FORBIDDEN_TOKENS = [
    "directora",
    "aurector",
    "scrutexity-authority-engine",
    "node",
    "graph patch",
    "graph_patch",
    "engine_run",
    "authority_brief_node",
    "provider_brief_node",
    "owner_brief_node",
    "render_seedance",
    "quality_render",
    "telemetry_finalize",
    "render_bundle",
    "pytest",
    "smoke_test",
]


# The bare word "node" appears in legitimate clinical contexts (lymph
# node, etc.) so the runtime drift guard only checks underscore-slug
# variants. These tests cover both the slug variants and the standalone
# tokens (excluding bare "node").
SLUG_AND_STANDALONE_TOKENS = [
    "directora",
    "aurector",
    "scrutexity-authority-engine",
    "graph patch",
    "graph_patch",
    "engine_run",
    "authority_brief_node",
    "provider_brief_node",
    "owner_brief_node",
    "render_seedance",
    "quality_render",
    "telemetry_finalize",
    "render_bundle",
    "pytest",
    "smoke_test",
]


def _flatten(obj):
    """Yield every string value in a nested dict/list."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _flatten(v)
    elif isinstance(obj, str):
        yield obj


def test_internal_tokens_list_contains_required_entries():
    for token in SLUG_AND_STANDALONE_TOKENS:
        assert token in lang.INTERNAL_TOKENS, (
            f"Internal token list is missing required entry: {token!r}"
        )


def test_contains_internal_tokens_detects_each_slug():
    for token in SLUG_AND_STANDALONE_TOKENS:
        assert lang.contains_internal_tokens(f"oops {token} oops") == [token] or \
               token in lang.contains_internal_tokens(f"oops {token} oops")


def test_provider_brief_output_has_no_internal_tokens(
    sample_receipt, sample_clinic_context
):
    """The Elite fixture must produce a Provider Brief that names zero
    internal module / framework tokens (excluding bare 'node')."""
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    review_summary = [
        {
            "index": 0,
            "reviewer_role": "Compliance Reviewer",
            "concern_type": "claim-risk review",
            "finding": "Body asserts a supported (with provider review) outcome.",
            "recommended_fix": "Replace with provider-reviewed phrasing.",
            "risk_level": "high",
            "score": 0.92,
            "selected_recommendation": True,
            "is_winner": True,
            "debug_ecosystem": "deepseek",
            "debug_ecosystem_label": "DeepSeek",
        }
    ]
    snippet = export.render_provider_brief(
        brief,
        review_summary=review_summary,
        ledger_summary={"by_kind": {}, "claim_risk_count": 0,
                        "human_approval_required_count": 0,
                        "render_fallback_count": 0},
        personas=AUTHORITY_REVIEW_PERSONAS,
    )
    output_text = json.dumps(snippet).lower()
    for token in SLUG_AND_STANDALONE_TOKENS:
        assert token not in output_text, (
            f"Drift guard: '{token}' leaked into Provider Brief output"
        )


def test_owner_brief_output_has_no_internal_tokens(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    snippet = export.render_owner_brief(brief, ledger_summary={
        "by_kind": {}, "claim_risk_count": 0,
        "human_approval_required_count": 0,
        "render_fallback_count": 0,
    })
    output_text = json.dumps(snippet).lower()
    for token in SLUG_AND_STANDALONE_TOKENS:
        assert token not in output_text, (
            f"Drift guard: '{token}' leaked into Owner Brief output"
        )


def test_asset_bundle_has_no_internal_tokens(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    bundle = export.render_bundle(brief, drafted={
        "short_form_script": "Treatment-specific content for the consult.",
        "faq_block": "Q: A: see provider for assessment.",
        "gbp_post": "Premium clinic, treatment-level visibility.",
        "landing_page_section": "Section copy.",
        "provider_quote": "Dr. K: We tailor each consult.",
    })
    output_text = json.dumps(bundle).lower()
    for token in SLUG_AND_STANDALONE_TOKENS:
        assert token not in output_text, (
            f"Drift guard: '{token}' leaked into Asset Bundle"
        )


def test_assert_no_internal_tokens_raises_when_violated():
    with pytest.raises(AssertionError):
        lang.assert_no_internal_tokens(
            "this contains Directora references",
            where="test_surface",
        )


def test_assert_no_internal_tokens_passes_on_clean_text():
    lang.assert_no_internal_tokens(
        "This treatment summary is provider-led and claim-safe.",
        where="test_surface",
    )
