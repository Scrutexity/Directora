"""Provider Brief variant tests (v3.3)."""
from __future__ import annotations

import pytest

from directora.nodes import provider_brief_node
from directora.scrutexity import authority_brief as ab
from directora.scrutexity import export
from directora.scrutexity.personas import AUTHORITY_REVIEW_PERSONAS
from directora.telemetry import outcome as ledger


_FAKE_REVIEW_SUMMARY = [
    {
        "index": 0,
        "reviewer_role": "Compliance Reviewer",
        "concern_type": "claim-risk review",
        "finding": "Body asserts a guaranteed outcome.",
        "recommended_fix": "Replace with provider-reviewed phrasing.",
        "risk_level": "high",
        "score": 0.92,
        "selected_recommendation": True,
        "is_winner": True,
        "debug_ecosystem": "deepseek",
        "debug_ecosystem_label": "DeepSeek",
    },
    {
        "index": 1,
        "reviewer_role": "Patient Trust Reviewer",
        "concern_type": "patient-experience trust",
        "finding": "Tone reads marketing-first.",
        "recommended_fix": "Re-anchor on provider voice and consult invitation.",
        "risk_level": "medium",
        "score": 0.78,
        "selected_recommendation": False,
        "is_winner": False,
        "debug_ecosystem": "qwen",
        "debug_ecosystem_label": "Qwen",
    },
]


def _brief(sample_receipt, sample_clinic_context):
    return ab.build_authority_brief(sample_receipt, sample_clinic_context)


def test_required_fields_present(sample_receipt, sample_clinic_context):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(
        brief,
        review_summary=_FAKE_REVIEW_SUMMARY,
        ledger_summary={
            "by_kind": {"asset_drafted": 5},
            "claim_risk_count": 2,
            "human_approval_required_count": 1,
            "render_fallback_count": 0,
        },
        personas=AUTHORITY_REVIEW_PERSONAS,
    )
    for key in (
        "asset_type",
        "label",
        "headline",
        "provider_facing_summary",
        "claim_risk_review_checklist",
        "suggested_safe_language",
        "selected_recommendation",
        "approval_required",
        "human_approval_status",
        "ledger_counts",
        "next_actions",
        "clinic_name",
        "treatment",
        "market",
        "Primary Visibility Gap",
        "First Fix I'd Prioritize",
        "claim_risk_notes",
        "disclaimer",
    ):
        assert key in snippet, f"missing required field: {key}"
    assert snippet["asset_type"] == "provider_brief_snippet"
    assert snippet["label"] == "Provider Brief"


def test_headline_includes_treatment_and_clinic(sample_receipt, sample_clinic_context):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, _FAKE_REVIEW_SUMMARY)
    assert "Morpheus8" in snippet["headline"]
    assert "Example Aesthetics NYC" in snippet["headline"]
    assert "Provider Brief" in snippet["headline"]


def test_claim_risk_checklist_includes_baseline_and_receipt_notes(
    sample_receipt, sample_clinic_context
):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, _FAKE_REVIEW_SUMMARY)
    checklist = snippet["claim_risk_review_checklist"]
    # Baseline items.
    assert any("guaranteed-outcome" in q for q in checklist)
    assert any("PHI-minimizing" in q for q in checklist)
    # Receipt-specific notes — each derived into a checklist question.
    assert any("guaranteed results" in q for q in checklist)
    assert any("before/after" in q for q in checklist)


def test_suggested_safe_language_from_personas(sample_receipt, sample_clinic_context):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(
        brief, _FAKE_REVIEW_SUMMARY, personas=AUTHORITY_REVIEW_PERSONAS
    )
    safe = snippet["suggested_safe_language"]
    assert safe, "safe language list must not be empty"
    # Pull-through from Compliance Reviewer rules.
    assert any("provider review" in s.lower() for s in safe)
    assert any("phi-minimizing" in s.lower() for s in safe)


def test_selected_recommendation_surfaces_marked_turn(
    sample_receipt, sample_clinic_context
):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, _FAKE_REVIEW_SUMMARY)
    sel = snippet["selected_recommendation"]
    assert sel is not None
    assert sel["reviewer_role"] == "Compliance Reviewer"
    assert sel["selected_recommendation"] is True


def test_selected_recommendation_falls_back_to_highest_risk(
    sample_receipt, sample_clinic_context
):
    """If no turn is marked, the highest-risk turn surfaces — so the
    provider always has a starting point."""
    review = [
        {**t, "selected_recommendation": False, "is_winner": False}
        for t in _FAKE_REVIEW_SUMMARY
    ]
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, review)
    sel = snippet["selected_recommendation"]
    assert sel is not None
    assert sel["risk_level"] == "high"  # Compliance Reviewer wins on risk_rank.


def test_missing_review_summary_does_not_break(
    sample_receipt, sample_clinic_context
):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, review_summary=None)
    assert snippet["selected_recommendation"] is None
    # The provider summary still includes the basics.
    summary = snippet["provider_facing_summary"]
    assert "Morpheus8" in summary
    assert "Primary Visibility Gap" in summary


def test_disclaimer_and_approval_status_present(
    sample_receipt, sample_clinic_context
):
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, _FAKE_REVIEW_SUMMARY)
    assert snippet["disclaimer"].startswith("Not a clinical")
    assert snippet["human_approval_status"] == "human approval required"
    assert snippet["approval_required"] is True


def test_no_forbidden_language_in_provider_facing_summary(
    sample_receipt, sample_clinic_context
):
    """If the provider summary ever picks up forbidden words via the
    selected recommendation, they should be scrubbed before display."""
    review = [
        {
            **_FAKE_REVIEW_SUMMARY[0],
            "finding": "We guarantee dramatic results.",
            "recommended_fix": "Avoid guarantee language.",
        }
    ]
    brief = _brief(sample_receipt, sample_clinic_context)
    snippet = export.render_provider_brief(brief, review)
    text = snippet["provider_facing_summary"]
    assert "guarantee" not in text.lower()
    assert "guaranteed" not in text.lower()


class _NodeState:
    """Lightweight state for node-level tests — only the fields the
    provider_brief_node and authority_brief_node actually read."""

    def __init__(self, **kw):
        self.run_id = "run-test"
        self.receipt_input = None
        self.clinic_context = None
        self.authority_review_summary = None
        self.authority_brief = None
        self.clinic_name = None
        self.treatment = None
        self.market = None
        self.approval_status = None
        self.telemetry = {"events": []}
        for k, v in kw.items():
            setattr(self, k, v)


def test_provider_brief_node_records_ledger_event(
    memory_ledger, sample_receipt, sample_clinic_context
):
    from directora.nodes import authority_brief_node

    state = _NodeState(
        receipt_input=sample_receipt,
        clinic_context=sample_clinic_context,
    )

    # Build the brief.
    brief_delta = authority_brief_node.run(state)
    state.authority_brief = brief_delta["authority_brief"]
    state.clinic_name = brief_delta["clinic_name"]
    state.treatment = brief_delta["treatment"]
    state.market = brief_delta["market"]

    # Inject the review summary.
    state.authority_review_summary = _FAKE_REVIEW_SUMMARY

    delta = provider_brief_node.run(state)
    snippet = delta["provider_brief"]
    assert snippet is not None
    assert snippet["asset_type"] == "provider_brief_snippet"

    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "provider_brief_ready" in kinds


def test_provider_brief_node_noop_in_generic_mode(memory_ledger):
    state = _NodeState()
    delta = provider_brief_node.run(state)
    assert delta["provider_brief"] is None
