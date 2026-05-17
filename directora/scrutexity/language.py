"""
Scrutexity language guards.

Centralises the forbidden-language list, the required Scrutexity phrasing,
and the standard compliance disclaimer so every clinic-facing surface
draws from the same source. Used by authority_brief, export, transcript,
and personas modules.

Public API:
    DISCLAIMER                       canonical clinic-facing disclaimer string
    FORBIDDEN_TERMS                  tuple of strings that must never appear
                                     in clinic-facing output
    REQUIRED_SCRUTEXITY_PHRASES      tuple of canonical phrasings to prefer
    CLINIC_FACING_NAME_REPLACEMENTS  dict of internal name -> clinic-facing name
    scrub_forbidden(text)            return text with forbidden terms neutralised
    normalize_language(text)         apply forbidden + name scrubs together
    contains_forbidden(text)         -> list[str] of any hits
    enforce_disclaimer(text)         ensure disclaimer appears once at the end
"""
from __future__ import annotations

import re
from typing import Iterable

DISCLAIMER = (
    "Not a clinical, legal, or regulatory assessment. "
    "Based on sampled prompt testing."
)

# Substring matches (case-insensitive). Keep this list aligned with the
# brand rules: never claim guarantees, never imply autonomous medical
# behaviour, never use hype/SEO-agency language.
FORBIDDEN_TERMS: tuple[str, ...] = (
    "invisible",
    # Order matters: "viral guarantee" and "guaranteed" must be neutralised
    # before the bare verb "guarantee" so we don't double-process them.
    "viral guarantee",
    "guaranteed",
    "guarantee",
    "dominate ai search",
    "dominate ai",
    "gaming the system",
    "displace competitors",
    "10x",
    "autonomous medical advice",
    "fully automated patient handling",
    "hipaa certified",
)

REQUIRED_SCRUTEXITY_PHRASES: tuple[str, ...] = (
    "Primary Visibility Gap",
    "Competitors Surfacing More Often",
    "Did not surface in this prompt set",
    "First Fix I'd Prioritize",
    "treatment-level visibility",
    "AI-assisted discovery",
    "governed workflows",
    "claim-risk review",
    "PHI-minimizing workflows",
    "human approval required",
    "owner brief",
)

# Internal engine names that must not appear in clinic-facing output.
CLINIC_FACING_NAME_REPLACEMENTS: dict[str, str] = {
    "Directora": "Scrutexity Authority Engine",
    "directora": "Scrutexity Authority Engine",
    "Aurector": "Scrutexity Authority Engine",
    "aurector": "Scrutexity Authority Engine",
    "Mirror Chamber": "Authority Review",
    "Debate Transcript": "Authority Review Summary",
    "Outcome Telemetry": "Governed Workflow Ledger",
    "Seedance render": "Quality Render Step",
    "Seedance Render": "Quality Render Step",
    "HappyHorse fallback": "Fallback Render Draft",
    "HappyHorse Fallback": "Fallback Render Draft",
}

# Drift-guard internal tokens — any occurrence of these (case-insensitive)
# in provider-facing output is a bug. The drift guard checks every
# clinic-facing surface emitted by the API, the export module, and the
# Authority Review Summary.
INTERNAL_TOKENS: tuple[str, ...] = (
    "directora",
    "aurector",
    "scrutexity-authority-engine",
    "graph patch",
    "graph_patch",
    "engine_run",
    "authority_brief_node",
    "provider_brief_node",
    "owner_brief_node",
    "render_seedance",
    "quality_render",
    "telemetry_finalize",
    "render_bundle",
    "pytest",
    "smoke_test",
)


def contains_internal_tokens(text: str) -> list[str]:
    """Return every internal-token substring found in `text`.

    The bare word "node" appears in legitimate clinical contexts (lymph
    node, etc.) so we detect it only when used as an engine slug
    suffix — checked via the underscore-suffixed variants above.
    Case-insensitive matching across the rest.
    """
    if not text:
        return []
    low = str(text).lower()
    return [tok for tok in INTERNAL_TOKENS if tok in low]


def assert_no_internal_tokens(text: str, *, where: str = "<unknown>") -> None:
    """Raise AssertionError listing every offending token if any are present."""
    hits = contains_internal_tokens(text)
    if hits:
        raise AssertionError(
            f"Drift guard: internal tokens leaked into {where}: {hits}"
        )

# Per-term neutralisation. Keys are matched case-insensitively against the
# forbidden list above; values are the safe replacements we substitute in.
_FORBIDDEN_REPLACEMENTS: dict[str, str] = {
    "invisible": "less visible in AI-assisted discovery",
    "viral guarantee": "claim-safe content",
    "guaranteed": "supported (with provider review)",
    "guarantee": "support (with provider review)",
    "dominate ai search": "improve treatment-level visibility",
    "dominate ai": "improve treatment-level visibility",
    "gaming the system": "operating within governed workflows",
    "displace competitors": "close the Primary Visibility Gap",
    "10x": "materially",
    "autonomous medical advice": "provider-reviewed guidance",
    "fully automated patient handling": "PHI-minimizing workflows with human approval",
    "hipaa certified": "PHI-minimizing workflows",
}


def contains_forbidden(text: str) -> list[str]:
    """Return the list of forbidden terms found in `text` (case-insensitive)."""
    if not text:
        return []
    low = text.lower()
    return [t for t in FORBIDDEN_TERMS if t in low]


def scrub_forbidden(text: str) -> str:
    """Replace forbidden terms with claim-safe equivalents, preserving case
    only loosely. We always emit the safe lower-case form; clinic surfaces
    should re-titlecase as needed."""
    if not text:
        return text
    out = text
    for term, replacement in _FORBIDDEN_REPLACEMENTS.items():
        # case-insensitive whole-substring replace
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        out = pattern.sub(replacement, out)
    return out


def _scrub_internal_names(text: str) -> str:
    if not text:
        return text
    out = text
    for internal, public in CLINIC_FACING_NAME_REPLACEMENTS.items():
        out = out.replace(internal, public)
    return out


def normalize_language(text: str) -> str:
    """Apply both forbidden-term scrubbing and internal-name replacement."""
    return _scrub_internal_names(scrub_forbidden(text))


def normalize_iterable(items: Iterable[str]) -> list[str]:
    return [normalize_language(x) for x in items]


def enforce_disclaimer(text: str) -> str:
    """Ensure the canonical disclaimer appears exactly once at the end."""
    if not text:
        return DISCLAIMER
    if DISCLAIMER in text:
        return text.rstrip() + "\n"  # already present, leave it alone
    return text.rstrip() + "\n\n" + DISCLAIMER + "\n"
