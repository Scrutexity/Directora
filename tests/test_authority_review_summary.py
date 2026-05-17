"""Authority Review Summary tests (refactored transcript module)."""
from __future__ import annotations

from dataclasses import dataclass

from directora.mirror import transcript


@dataclass
class _Persona:
    name: str
    ecosystem: str = "deepseek"
    role: str | None = None


@dataclass
class _Turn:
    persona: _Persona
    content: str
    recommended_fix: str = "Recommend provider review."
    risk_level: str = "medium"
    score: float | None = 0.8
    reviewer_role: str | None = None
    concern_type: str = "claim-risk review"


def _state_with_turns():
    return _S(
        turns=[
            _Turn(
                _Persona("Ada", ecosystem="deepseek"),
                "Treatment claim seems strong without provider review.",
                risk_level="high",
                reviewer_role="Compliance Reviewer",
            ),
            _Turn(
                _Persona("Bo", ecosystem="qwen"),
                "Patient might assume guaranteed outcome.",
                recommended_fix="Soften wording, mention provider assessment.",
                risk_level="medium",
                score=0.6,
                reviewer_role="Patient Trust Reviewer",
            ),
            _Turn(
                _Persona("Cy", ecosystem="kimi"),
                "CTA could be more treatment-specific.",
                recommended_fix="Use 'Book a Morpheus8 consult'.",
                risk_level="low",
                reviewer_role="Conversion Strategist",
            ),
        ],
        winner_role="Compliance Reviewer",
    )


class _S:
    def __init__(self, turns, winner_role=None):
        self.authority_review = turns
        self.debate = turns
        self.selected_recommendation = winner_role
        self.debate_winner = None


def test_reviewer_roles_drive_clinic_facing_output():
    state = _state_with_turns()
    turns = transcript.build_review_summary(state)
    md = transcript.to_markdown(turns)
    html = transcript.to_html(turns)
    # Reviewer roles appear in client-facing output...
    assert "Compliance Reviewer" in md
    assert "Patient Trust Reviewer" in md
    # ...and ecosystem badges do NOT lead the clinic-facing output.
    for badge in ("DeepSeek", "Qwen", "Kimi", "Grok"):
        assert badge not in md
        assert badge not in html


def test_risk_levels_render_in_markdown_and_html():
    state = _state_with_turns()
    turns = transcript.build_review_summary(state)
    md = transcript.to_markdown(turns)
    html = transcript.to_html(turns)
    assert "risk High" in md or "risk high" in md.lower()
    assert "risk Medium" in md or "risk medium" in md.lower()
    assert "authority-review__risk--high" in html
    assert "authority-review__risk--medium" in html
    assert "authority-review__risk--low" in html


def test_selected_recommendation_is_marked():
    state = _state_with_turns()
    turns = transcript.build_review_summary(state)
    md = transcript.to_markdown(turns)
    html = transcript.to_html(turns)
    assert any(t.selected_recommendation for t in turns)
    assert "Selected Recommendation" in md
    assert "authority-review__turn--selected" in html


def test_disclaimer_present_in_markdown_and_html():
    state = _state_with_turns()
    turns = transcript.build_review_summary(state)
    md = transcript.to_markdown(turns)
    html = transcript.to_html(turns)
    assert "Not a clinical, legal, or regulatory assessment" in md
    assert "Not a clinical, legal, or regulatory assessment" in html


def test_debug_ecosystem_in_json_only():
    state = _state_with_turns()
    delta = transcript.attach_to_state(state)
    raw = delta["authority_review_summary"]
    # JSON payload still has the debug field for engineering...
    assert any("debug_ecosystem" in t for t in raw)
    # ...but the rendered markdown does not.
    assert "deepseek" not in delta["authority_review_summary_markdown"].lower()


def test_attach_to_state_also_writes_legacy_keys():
    """Legacy v3.0 keys must still appear so older callers don't break."""
    state = _state_with_turns()
    delta = transcript.attach_to_state(state)
    assert "transcript_visible" in delta
    assert "transcript_markdown" in delta
    assert "authority_review_summary" in delta
    assert "authority_review_summary_markdown" in delta


def test_markdown_title_uses_scrutexity_phrasing():
    state = _state_with_turns()
    turns = transcript.build_review_summary(state)
    md = transcript.to_markdown(turns)
    assert md.startswith("## Authority Review Summary")
