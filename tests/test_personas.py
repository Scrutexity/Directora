"""Authority Review persona tests."""
from __future__ import annotations

import pytest

from directora.scrutexity import personas


def test_six_canonical_personas_present():
    names = [p.name for p in personas.AUTHORITY_REVIEW_PERSONAS]
    assert names == [
        "Compliance Reviewer",
        "Patient Trust Reviewer",
        "Conversion Strategist",
        "AI Visibility Reviewer",
        "Medical Aesthetics Brand Guardian",
        "Clinic Owner Reviewer",
    ]


def test_weights_sum_to_one_within_tolerance():
    total = personas.total_weight()
    assert 0.999 <= total <= 1.001


def test_lookup_is_case_insensitive():
    p = personas.get_persona("compliance reviewer")
    assert p.name == "Compliance Reviewer"


def test_lookup_unknown_raises():
    with pytest.raises(KeyError):
        personas.get_persona("Imaginary Reviewer")


def test_favored_dimensions_priority_order():
    favored = personas.favored_dimensions()
    assert favored[0] == "clarity"
    assert "treatment_level_relevance" in favored
    assert "claim_safety" in favored


def test_penalized_dimensions_contain_hype_and_guarantees():
    penalised = personas.penalized_dimensions()
    assert "hype" in penalised
    assert "guaranteed_outcomes" in penalised
    assert "generic_receptionist_or_seo_tone" in penalised


def test_score_finding_within_bounds():
    p = personas.get_persona("Compliance Reviewer")
    high = personas.score_finding(persona=p, favored_signal=1.0, penalized_signal=0.0)
    low = personas.score_finding(persona=p, favored_signal=0.0, penalized_signal=1.0)
    mid = personas.score_finding(persona=p, favored_signal=0.5, penalized_signal=0.5)
    assert 0.0 <= low < mid < high <= 1.0


def test_fail_conditions_include_guarantee_check():
    p = personas.get_persona("Compliance Reviewer")
    assert any("guaranteed" in f.lower() for f in p.fail_conditions)
