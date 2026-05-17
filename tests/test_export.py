"""Scrutexity export layer tests."""
from __future__ import annotations

import pytest

from directora.scrutexity import authority_brief as ab
from directora.scrutexity import export


def test_render_asset_includes_required_metadata(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    asset = export.render_asset(
        "short_form_script", brief, "Hook line and provider context."
    )
    for field in (
        "clinic_name",
        "treatment",
        "market",
        "Primary Visibility Gap",
        "First Fix I'd Prioritize",
        "claim_risk_notes",
        "approval_required",
        "disclaimer",
    ):
        assert field in asset
    assert asset["disclaimer"].startswith("Not a clinical")


def test_render_asset_rejects_unknown_type(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    with pytest.raises(ValueError):
        export.render_asset("podcast_episode", brief, "body")


def test_render_bundle_covers_all_requested_outputs(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    drafted = {
        "short_form_script": "Provider-led hook for Morpheus8.",
        "faq_block": "Q: What is Morpheus8? A: A treatment...",
        "gbp_post": "Treatment-level update.",
        "landing_page_section": "Section copy.",
        "provider_quote": "Dr. X: This treatment is supported with provider review.",
    }
    bundle = export.render_bundle(brief, drafted)
    asset_types = [a["asset_type"] for a in bundle]
    for at in (
        "short_form_script",
        "faq_block",
        "gbp_post",
        "landing_page_section",
        "provider_quote",
    ):
        assert at in asset_types


def test_render_bundle_flags_missing_bodies(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    bundle = export.render_bundle(brief, drafted={})
    assert all(a.get("body_missing") for a in bundle)


def test_forbidden_language_scrubbed_in_body(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    asset = export.render_asset(
        "gbp_post",
        brief,
        "We guarantee you will dominate AI search and 10x your patients.",
    )
    body = asset["body"]
    assert "guaranteed" not in body.lower()
    assert "guarantee" not in body.lower()
    assert "10x" not in body.lower()
    assert "dominate ai" not in body.lower()


def test_owner_brief_snippet_summarises_ledger(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    ledger_summary = {
        "by_kind": {"asset_drafted": 5, "claim_risk_flagged": 2},
        "claim_risk_count": 2,
        "human_approval_required_count": 1,
        "render_fallback_count": 1,
        "treatments_processed": ["Morpheus8"],
    }
    snippet = export.render_owner_brief(brief, ledger_summary)
    assert snippet["asset_type"] == "owner_brief_snippet"
    assert snippet["ledger_counts"]["claim_risk_flagged"] == 2
    assert snippet["ledger_counts"]["assets_drafted"] == 5
    assert snippet["human_approval_status"] == "human approval required"
    assert "Primary Visibility Gap" in snippet["summary"]
    assert "Morpheus8" in snippet["summary"]
    assert snippet["disclaimer"].startswith("Not a clinical")


def test_owner_brief_handles_missing_ledger_summary(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    snippet = export.render_owner_brief(brief, None)
    assert snippet["ledger_counts"]["assets_drafted"] == 0
    assert snippet["ledger_counts"]["claim_risk_flagged"] == 0
