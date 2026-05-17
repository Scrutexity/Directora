"""AI Visibility Receipt schema tests (v3.2 protection layer)."""
from __future__ import annotations

import pytest

from directora.scrutexity import schema
from directora.scrutexity.schema import ReceiptValidationError


def _valid_receipt(**overrides) -> dict:
    base = {
        "clinic_name": "Elite Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "treatment": "Morpheus8",
        "primary_visibility_gap": (
            "Did not surface in this prompt set for Morpheus8 acne scars Upper East Side"
        ),
        "first_fix_id_prioritize": (
            "Create provider-led Morpheus8 acne scar content with safe expectations "
            "and a consult CTA"
        ),
        "competitors_surfacing_more_often": ["Competitor A", "Competitor B"],
        "claim_risk_notes": [
            "Avoid guaranteed skin tightening claims",
            "Avoid unqualified before/after promises",
        ],
    }
    base.update(overrides)
    return base


def test_valid_receipt_passes_strict():
    out = schema.validate_receipt(_valid_receipt())
    assert out["clinic_name"] == "Elite Aesthetics NYC"
    assert out["treatment"] == "Morpheus8"
    assert "Competitor A" in out["competitors_surfacing_more_often"]


def test_missing_clinic_name_raises():
    bad = _valid_receipt()
    del bad["clinic_name"]
    with pytest.raises(ReceiptValidationError) as exc:
        schema.validate_receipt(bad)
    fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.value.errors})
    assert "clinic_name" in fields


def test_missing_market_raises():
    bad = _valid_receipt()
    del bad["market"]
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_missing_primary_visibility_gap_raises():
    bad = _valid_receipt()
    del bad["primary_visibility_gap"]
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_missing_first_fix_raises():
    bad = _valid_receipt()
    del bad["first_fix_id_prioritize"]
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_empty_string_required_field_raises():
    bad = _valid_receipt(clinic_name="")
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_single_treatments_tested_infers_treatment():
    """A receipt with treatments_tested=[X] but no `treatment` is unambiguous."""
    bad = _valid_receipt()
    del bad["treatment"]
    bad["treatments_tested"] = ["Morpheus8"]
    out = schema.validate_receipt(bad)
    assert out["treatment"] == "Morpheus8"
    assert out["treatments_tested"] == ["Morpheus8"]


def test_multi_treatments_tested_without_explicit_treatment_raises():
    """The real Elite Aesthetics receipt shape: must specify focus explicitly."""
    bad = _valid_receipt()
    del bad["treatment"]
    bad["treatments_tested"] = ["Morpheus8", "lip filler", "Botox"]
    with pytest.raises(ReceiptValidationError) as exc:
        schema.validate_receipt(bad)
    assert "Ambiguous treatment focus" in str(exc.value) or any(
        "Ambiguous" in (e.get("msg") or "") for e in exc.value.errors
    )


def test_no_treatment_no_treatments_tested_raises():
    bad = _valid_receipt()
    del bad["treatment"]
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_unknown_content_output_raises():
    bad = _valid_receipt(content_outputs_needed=["short_form_script", "podcast_episode"])
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(bad)


def test_lenient_mode_returns_raw_with_flag():
    bad = _valid_receipt()
    del bad["clinic_name"]
    out = schema.validate_receipt(bad, strict=False)
    assert "_lenient_validation_failed" in out
    assert out.get("clinic_name") in (None, "")


def test_none_receipt_raises_in_strict_mode():
    with pytest.raises(ReceiptValidationError):
        schema.validate_receipt(None)


def test_none_receipt_lenient_returns_empty():
    out = schema.validate_receipt(None, strict=False)
    assert out == {}


def test_string_coerced_to_singleton_list_for_competitors():
    """Forgiving input coercion: a bare string becomes a one-item list."""
    raw = _valid_receipt(competitors_surfacing_more_often="Competitor A")
    out = schema.validate_receipt(raw)
    assert out["competitors_surfacing_more_often"] == ["Competitor A"]


def test_validation_error_to_dict_is_serialisable():
    bad = _valid_receipt()
    del bad["clinic_name"]
    try:
        schema.validate_receipt(bad)
    except ReceiptValidationError as exc:
        payload = exc.to_dict()
        assert "errors" in payload and isinstance(payload["errors"], list)
        assert "summary" in payload
        assert "clinic_name" in payload["summary"]
    else:
        pytest.fail("expected ReceiptValidationError")


def test_extra_fields_tolerated():
    """Future receipt versions may add fields — engine must not break."""
    raw = _valid_receipt(future_field="some new context")
    out = schema.validate_receipt(raw)
    assert out["future_field"] == "some new context"


def test_json_schema_exports():
    s = schema.json_schema()
    assert s["type"] == "object"
    required = set(s.get("required", []))
    # Pydantic marks required by absence of default — confirm the four core keys.
    for key in (
        "clinic_name",
        "market",
        "primary_visibility_gap",
        "first_fix_id_prioritize",
    ):
        assert key in required, f"{key} should be required in JSON Schema"
