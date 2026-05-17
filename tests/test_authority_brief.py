"""Authority Brief creation tests."""
from __future__ import annotations

import pytest

from directora.scrutexity import authority_brief as ab
from directora.scrutexity.schema import ReceiptValidationError


def test_receipt_maps_primary_visibility_gap(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    assert "Morpheus8 acne scars Upper East Side" in brief["primary_visibility_gap"]
    assert brief["treatment"] == "Morpheus8"
    assert brief["clinic_name"] == "Example Aesthetics NYC"
    assert brief["market"] == "Upper East Side, NYC"


def test_competitors_preserved(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    assert brief["competitors_surfacing_more_often"] == ["Competitor A", "Competitor B"]


def test_forbidden_language_normalised(sample_clinic_context):
    receipt = {
        "clinic_name": "Example Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "treatment": "Morpheus8",
        "primary_visibility_gap": "We are invisible and want to dominate AI search",
        "trust_gap": "Patients think results are guaranteed",
        "first_fix_id_prioritize": "Create provider-led content with safe expectations.",
        "claim_risk_notes": [],
    }
    brief = ab.build_authority_brief(receipt, sample_clinic_context)
    text = brief["primary_visibility_gap"] + " " + brief["trust_gap"]
    assert "invisible" not in text.lower()
    assert "dominate ai search" not in text.lower()
    assert "guaranteed" not in text.lower()
    # The neutralised replacement appears.
    assert "less visible in AI-assisted discovery" in brief["primary_visibility_gap"]


def test_missing_clinic_context_does_not_break(sample_receipt):
    """A valid receipt with no supplementary clinic_context still works
    because the receipt itself carries clinic_name and market."""
    brief = ab.build_authority_brief(sample_receipt, None)
    assert brief["clinic_name"] == "Example Aesthetics NYC"
    assert brief["market"] == "Upper East Side, NYC"
    assert brief["approval_required"] is True


def test_validation_flags_missing_required():
    report = ab.validate_authority_brief({"clinic_name": "X"})
    assert report["ok"] is False
    assert any("market" in e for e in report["errors"])
    assert any("treatment" in e for e in report["errors"])


def test_validation_passes_clean_brief(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    report = ab.validate_authority_brief(brief)
    assert report["ok"] is True
    assert report["errors"] == []


def test_default_content_outputs_filled_when_missing(sample_clinic_context):
    receipt = {
        "clinic_name": "Example Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "treatment": "Morpheus8",
        "primary_visibility_gap": "Did not surface in this prompt set",
        "first_fix_id_prioritize": "Provider-led content with safe expectations.",
        "claim_risk_notes": ["Avoid guaranteed results"],
        # content_outputs_needed intentionally omitted
    }
    brief = ab.build_authority_brief(receipt, sample_clinic_context)
    assert "short_form_script" in brief["content_outputs_needed"]
    assert "faq_block" in brief["content_outputs_needed"]
    assert "landing_page_section" in brief["content_outputs_needed"]


def test_unknown_content_outputs_raise_in_strict_mode(
    sample_receipt, sample_clinic_context
):
    """v3.2 change: an unknown asset slug is a structured validation error,
    not a silently-dropped value. Use strict=False to opt back into legacy
    best-effort behaviour."""
    sample_receipt["content_outputs_needed"] = [
        "short_form_script",
        "bogus_output",
        "gbp_post",
    ]
    with pytest.raises(ReceiptValidationError):
        ab.build_authority_brief(sample_receipt, sample_clinic_context)


def test_unknown_content_outputs_dropped_in_lenient_mode(
    sample_receipt, sample_clinic_context
):
    sample_receipt["content_outputs_needed"] = [
        "short_form_script",
        "bogus_output",
        "gbp_post",
    ]
    brief = ab.build_authority_brief(
        sample_receipt, sample_clinic_context, strict=False
    )
    assert "bogus_output" not in brief["content_outputs_needed"]
    assert "short_form_script" in brief["content_outputs_needed"]
    assert "gbp_post" in brief["content_outputs_needed"]
