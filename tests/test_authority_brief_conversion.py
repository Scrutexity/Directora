"""Authority Brief -> Directora input conversion tests."""
from __future__ import annotations

from directora.scrutexity import authority_brief as ab


def test_topic_combines_treatment_market_and_gap(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    di = ab.authority_brief_to_directora_input(brief)
    assert "Morpheus8" in di["topic"]
    assert "Upper East Side" in di["topic"]
    assert "Primary Visibility Gap" in di["topic"]


def test_claim_risk_notes_become_compliance_constraints(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    di = ab.authority_brief_to_directora_input(brief)
    for note in brief["claim_risk_notes"]:
        assert note in di["compliance_constraints"]
    # Canonical reinforcements always present.
    assert "Recommend provider review before publishing" in di["compliance_constraints"]
    assert "Preserve PHI-minimizing workflows" in di["compliance_constraints"]


def test_content_outputs_map_into_output_plan(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    di = ab.authority_brief_to_directora_input(brief)
    assert di["output_plan"] == brief["content_outputs_needed"]


def test_brand_kit_combines_clinic_tone_and_trust_gap(
    sample_receipt, sample_clinic_context
):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    di = ab.authority_brief_to_directora_input(brief)
    bk = di["brand_kit"]
    assert bk["name"] == brief["clinic_name"]
    assert bk["tone"] == brief["tone"]
    assert any(brief["trust_gap"] in v for v in bk["voice_notes"])
    assert bk["treatment"] == brief["treatment"]
    assert bk["market"] == brief["market"]


def test_creative_direction_is_first_fix(sample_receipt, sample_clinic_context):
    brief = ab.build_authority_brief(sample_receipt, sample_clinic_context)
    di = ab.authority_brief_to_directora_input(brief)
    assert di["creative_direction"] == brief["first_fix_id_prioritize"]
    assert di["mode"] == "scrutexity"
    assert di["approval_required"] is True
