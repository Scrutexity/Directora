"""
Scrutexity Authority Review personas.

These six reviewer roles drive the Authority Review layer. The transcript
module surfaces them in client-facing markdown/HTML; the scoring layer
uses their weights and fail conditions to decide whether a generated
asset can advance to Human Approval.

Public API:
    Persona                   dataclass with name, role, review_focus,
                              fail_conditions, scoring_weight,
                              safe_language_rules
    AUTHORITY_REVIEW_PERSONAS list[Persona] — the six canonical reviewers
    get_persona(name)         lookup helper (case-insensitive)
    favored_dimensions()      ordered list of dimensions Scrutexity favors
    penalized_dimensions()    ordered list of dimensions Scrutexity penalizes
    score_finding(...)        helper that combines persona weight with
                              dimension-level signal into a 0..1 score
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# Scoring dimensions, in priority order.
FAVORED_DIMENSIONS: tuple[str, ...] = (
    "clarity",
    "treatment_level_relevance",
    "claim_safety",
    "booking_intent",
    "provider_trust",
    "ai_assisted_discovery_usefulness",
)

PENALIZED_DIMENSIONS: tuple[str, ...] = (
    "hype",
    "guaranteed_outcomes",
    "generic_content",
    "weak_cta",
    "unsupported_medical_claims",
    "vague_treatment_language",
    "generic_receptionist_or_seo_tone",
)


@dataclass(frozen=True)
class Persona:
    name: str
    role: str
    review_focus: str
    fail_conditions: tuple[str, ...]
    scoring_weight: float
    safe_language_rules: tuple[str, ...]


# Six canonical Authority Review personas. Weights are normalised so they
# sum to 1.0 — Compliance and Patient Trust get the largest share because
# claim safety is the primary brand risk for medical aesthetics output.
AUTHORITY_REVIEW_PERSONAS: list[Persona] = [
    Persona(
        name="Compliance Reviewer",
        role="claim-risk review",
        review_focus=(
            "Flag guaranteed-outcome language, unsupported clinical claims, "
            "implied treatment suitability for a specific patient, and any "
            "wording that resembles personalized medical advice."
        ),
        fail_conditions=(
            "Contains a guaranteed outcome claim",
            "Implies treatment suitability for a specific patient",
            "Asserts a clinical result without provider review",
            "Uses HIPAA certified language without explicit verification",
        ),
        scoring_weight=0.25,
        safe_language_rules=(
            "Prefer 'supported (with provider review)' over 'guaranteed'",
            "Use 'PHI-minimizing workflows' rather than HIPAA marketing language",
            "Always recommend provider review before publishing",
        ),
    ),
    Persona(
        name="Patient Trust Reviewer",
        role="patient-experience trust",
        review_focus=(
            "Check that the asset reads as provider-led, sets realistic "
            "expectations, and respects patient autonomy. Penalize hype, "
            "pressure tactics, or before/after promises."
        ),
        fail_conditions=(
            "Uses pressure or scarcity language",
            "Promises before/after results without disclaimer",
            "Reads as marketing-first rather than provider-led",
        ),
        scoring_weight=0.20,
        safe_language_rules=(
            "Lead with the provider voice or named clinical context",
            "Acknowledge that results vary and depend on assessment",
            "Invite a consult rather than implying outcome",
        ),
    ),
    Persona(
        name="Conversion Strategist",
        role="booking-friction reduction",
        review_focus=(
            "Make sure each asset has a treatment-specific CTA, surfaces "
            "the Primary Visibility Gap framing, and points toward a "
            "low-friction consult path."
        ),
        fail_conditions=(
            "CTA is generic ('Contact us') rather than treatment-specific",
            "No clear next step for the patient",
            "Buries the consult option below educational content",
        ),
        scoring_weight=0.15,
        safe_language_rules=(
            "Use 'Book a Morpheus8 consult' over 'Contact us'",
            "Frame CTA as a consult, not a transaction",
            "Keep CTA above the fold on landing-page outputs",
        ),
    ),
    Persona(
        name="AI Visibility Reviewer",
        role="treatment-level visibility",
        review_focus=(
            "Score how well the asset addresses the Primary Visibility Gap "
            "and whether it improves AI-assisted discovery for the treatment "
            "+ market combination."
        ),
        fail_conditions=(
            "Does not name the treatment in the first 30 words",
            "Does not reference the market or geography",
            "Reads identically to a competitor asset",
        ),
        scoring_weight=0.15,
        safe_language_rules=(
            "Name the treatment and market explicitly",
            "Reference the patient intent stated in the brief",
            "Avoid hype that would not be cited by an AI assistant",
        ),
    ),
    Persona(
        name="Medical Aesthetics Brand Guardian",
        role="brand voice integrity",
        review_focus=(
            "Defend the premium-clinical Scrutexity tone: clinical, premium, "
            "trust-first, non-hype. Reject anything that sounds like a "
            "generic AI receptionist or SEO agency."
        ),
        fail_conditions=(
            "Tone slips into hype or SEO-speak",
            "Sounds like a generic chatbot or receptionist script",
            "Contradicts the brand kit voice notes",
        ),
        scoring_weight=0.15,
        safe_language_rules=(
            "Default to clinical and trust-first phrasing",
            "Prefer specific provider proof points over adjectives",
            "Avoid superlatives unless quoted from a provider",
        ),
    ),
    Persona(
        name="Clinic Owner Reviewer",
        role="owner-proof workflow",
        review_focus=(
            "Read the asset as if the clinic owner will see it on Monday: "
            "is it ready for human approval, does it include the "
            "claim-risk notes and approval status, and would the owner "
            "feel safe publishing it?"
        ),
        fail_conditions=(
            "Approval status is missing or unclear",
            "Claim-risk notes are absent from the export bundle",
            "Owner would need additional context to publish safely",
        ),
        scoring_weight=0.10,
        safe_language_rules=(
            "Surface approval status near the top of any owner-facing summary",
            "Include the disclaimer on every export",
            "Make the First Fix I'd Prioritize explicit and singular",
        ),
    ),
]

# Cached lookup table.
_BY_NAME = {p.name.lower(): p for p in AUTHORITY_REVIEW_PERSONAS}


def get_persona(name: str) -> Persona:
    try:
        return _BY_NAME[name.lower()]
    except KeyError as exc:
        raise KeyError(
            f"Unknown Authority Review persona: {name!r}. "
            f"Known: {sorted(p.name for p in AUTHORITY_REVIEW_PERSONAS)}"
        ) from exc


def favored_dimensions() -> tuple[str, ...]:
    return FAVORED_DIMENSIONS


def penalized_dimensions() -> tuple[str, ...]:
    return PENALIZED_DIMENSIONS


def score_finding(
    *,
    persona: Persona | str,
    favored_signal: float = 0.0,
    penalized_signal: float = 0.0,
) -> float:
    """Combine a persona's weight with favored/penalized signal into a
    0..1 score. `favored_signal` and `penalized_signal` are expected to
    be normalised [0, 1] indicators provided by the scoring node.
    """
    p = persona if isinstance(persona, Persona) else get_persona(persona)
    raw = (favored_signal - penalized_signal) * p.scoring_weight
    # Clamp into [0, 1] and rebase from [-weight, +weight] to [0, weight*2].
    rebased = (raw + p.scoring_weight) / (2 * p.scoring_weight or 1.0)
    return max(0.0, min(1.0, rebased))


def total_weight(personas: Iterable[Persona] | None = None) -> float:
    """Sum of scoring_weight across the persona set (defaults to all six)."""
    pool = list(personas) if personas is not None else AUTHORITY_REVIEW_PERSONAS
    return round(sum(p.scoring_weight for p in pool), 6)
