"""Language guard tests — forbidden term scrubbing, name replacement,
and disclaimer enforcement."""
from __future__ import annotations

from directora.scrutexity import language as lang


def test_forbidden_terms_detected_case_insensitive():
    hits = lang.contains_forbidden("This is GUARANTEED to be invisible.")
    assert "guaranteed" in hits
    assert "invisible" in hits


def test_forbidden_terms_replaced_with_safe_equivalents():
    out = lang.scrub_forbidden(
        "Guaranteed results. Invisible to AI. Will 10x bookings."
    )
    assert "guaranteed" not in out.lower()
    assert "invisible" not in out.lower()
    assert "10x" not in out.lower()
    assert "supported (with provider review)" in out
    assert "less visible in AI-assisted discovery" in out


def test_internal_engine_names_replaced_in_normalize():
    out = lang.normalize_language(
        "Directora and Aurector are great, the Mirror Chamber is fast."
    )
    assert "Directora" not in out
    assert "Aurector" not in out
    assert "Mirror Chamber" not in out
    assert "Scrutexity Authority Engine" in out
    assert "Authority Review" in out


def test_normalize_handles_empty_and_none():
    assert lang.normalize_language("") == ""
    # Defensive: should not crash even on None-ish via str() upstream.
    assert lang.scrub_forbidden("") == ""


def test_enforce_disclaimer_adds_once():
    text = "Body of the asset."
    once = lang.enforce_disclaimer(text)
    twice = lang.enforce_disclaimer(once)
    # Disclaimer present...
    assert "Not a clinical, legal, or regulatory assessment" in once
    # ...exactly once, even when invoked repeatedly.
    assert twice.count("Not a clinical, legal, or regulatory assessment") == 1


def test_required_scrutexity_phrases_are_canonical():
    for phrase in (
        "Primary Visibility Gap",
        "Competitors Surfacing More Often",
        "First Fix I'd Prioritize",
        "treatment-level visibility",
        "AI-assisted discovery",
        "governed workflows",
        "PHI-minimizing workflows",
        "human approval required",
        "owner brief",
    ):
        assert phrase in lang.REQUIRED_SCRUTEXITY_PHRASES


def test_hipaa_certified_neutralised():
    out = lang.scrub_forbidden("We are HIPAA Certified.")
    assert "hipaa certified" not in out.lower()
    assert "PHI-minimizing workflows" in out
