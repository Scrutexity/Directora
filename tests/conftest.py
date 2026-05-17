"""Shared fixtures for the Scrutexity Authority Engine test suite."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from directora.telemetry import outcome


@dataclass
class FakeState:
    run_id: str = "run-test"
    tier: str = "fast"
    clinic_name: str | None = None
    treatment: str | None = None
    market: str | None = None
    primary_visibility_gap: str | None = None
    competitors_surfacing_more_often: list[str] = field(default_factory=list)
    first_fix_id_prioritize: str | None = None
    claim_risk_notes: list[str] = field(default_factory=list)
    approval_status: str | None = None
    receipt_input: dict | None = None
    clinic_context: dict | None = None
    authority_brief: dict | None = None
    debate: list = field(default_factory=list)
    authority_review: list = field(default_factory=list)
    selected_recommendation: object | None = None
    debate_winner: object | None = None
    shot_plan: list = field(default_factory=list)
    prompt: str = "treatment-level authority for Morpheus8"
    use_seedance: bool = True
    telemetry: dict = field(default_factory=lambda: {"events": []})


@pytest.fixture(autouse=True)
def memory_ledger():
    """Every test gets a fresh in-memory Governed Workflow Ledger."""
    sink = outcome.MemorySink()
    outcome.reset_sink_for_tests(sink)
    yield sink
    outcome.reset_sink_for_tests(None)


@pytest.fixture
def sample_receipt() -> dict:
    """A realistic AI Visibility Receipt with the canonical fields.

    Includes the four schema-required keys: clinic_name, market,
    primary_visibility_gap, first_fix_id_prioritize — plus a focus
    treatment. Optional context fields follow.
    """
    return {
        "clinic_name": "Example Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "treatment": "Morpheus8",
        "primary_visibility_gap": (
            "Did not surface in this prompt set for Morpheus8 acne scars Upper East Side"
        ),
        "visibility_gap": "Did not surface in this prompt set",
        "competitors_surfacing_more_often": ["Competitor A", "Competitor B"],
        "patient_intent": "Acne scar treatment research with booking intent",
        "trust_gap": "Treatment page lacks provider proof and recovery expectations",
        "booking_friction": "CTA is below the fold or not treatment-specific",
        "claim_risk_notes": [
            "Avoid guaranteed results",
            "Avoid unqualified before/after promises",
            "Avoid implying clinical outcome certainty",
        ],
        "first_fix_id_prioritize": (
            "Create provider-led educational content around Morpheus8 for acne scars "
            "with safe expectations and a consult CTA"
        ),
        "content_outputs_needed": [
            "short_form_script",
            "faq_block",
            "gbp_post",
            "landing_page_section",
            "provider_quote",
        ],
    }


@pytest.fixture
def sample_clinic_context() -> dict:
    return {
        "clinic_name": "Example Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "tone": "clinical, premium, trust-first, non-hype",
    }
