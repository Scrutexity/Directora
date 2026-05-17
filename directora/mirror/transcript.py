"""
Authority Review Summary (formerly: visible debate transcript).

Surfaces the multi-persona Authority Review layer in a form a clinic
owner can read. Clinic-facing markdown/HTML leads with reviewer role,
concern type, finding, recommended fix, risk level, and selection status.

Internal model ecosystem badges (DeepSeek / Qwen / Kimi / Grok) are
retained in the JSON payload for engineering debugging only — they are
NOT rendered in clinic-facing markdown/HTML.

Public API:
    VisibleTurn                  dataclass — one Authority Review finding
    build_review_summary(state)  pure builder
    to_markdown(turns)           clinic-facing markdown
    to_html(turns)               clinic-facing HTML with risk classes
    attach_to_state(state)       LangGraph node entry point

The module name and the LangGraph node binding remain `transcript` for
backwards compatibility with v3.0 graph wiring. The exported strings and
labels all use Scrutexity language.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal

from directora.scrutexity import language as _lang

RiskLevel = Literal["low", "medium", "high"]

# Risk-level styling for HTML output.
_RISK_CLASS: dict[RiskLevel, str] = {
    "low": "authority-review__risk--low",
    "medium": "authority-review__risk--medium",
    "high": "authority-review__risk--high",
}
_RISK_LABEL: dict[RiskLevel, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}

# Ecosystem badge metadata is retained for JSON debug output only.
# It is intentionally not surfaced in markdown/html.
_DEBUG_ECOSYSTEM_BADGE: dict[str, dict[str, str]] = {
    "deepseek": {"label": "DeepSeek", "glyph": "DS"},
    "qwen": {"label": "Qwen", "glyph": "QW"},
    "kimi": {"label": "Kimi", "glyph": "KM"},
    "grok": {"label": "Grok", "glyph": "GK"},
    "unknown": {"label": "Unknown", "glyph": "??"},
}


def _normalise_risk(value: Any) -> RiskLevel:
    v = (str(value) if value is not None else "").strip().lower()
    if v in ("low", "medium", "high"):
        return v  # type: ignore[return-value]
    return "low"


def _normalise_ecosystem(value: Any) -> str:
    v = (str(value) if value is not None else "").strip().lower()
    return v if v in _DEBUG_ECOSYSTEM_BADGE else "unknown"


@dataclass
class VisibleTurn:
    index: int
    reviewer_role: str
    concern_type: str
    finding: str
    recommended_fix: str
    risk_level: RiskLevel
    score: float | None
    is_winner: bool                 # alias kept for backwards compatibility
    selected_recommendation: bool   # canonical clinic-facing flag
    # Debug-only fields — included in JSON, omitted from md/html.
    debug_ecosystem: str = "unknown"
    debug_ecosystem_label: str = "Unknown"

    def to_public_dict(self) -> dict:
        d = asdict(self)
        return d


def _resolve_reviewer_role(turn: Any) -> str:
    role = (
        getattr(turn, "reviewer_role", None)
        or getattr(getattr(turn, "persona", None), "role", None)
        or getattr(getattr(turn, "persona", None), "name", None)
        or "Authority Reviewer"
    )
    return str(role)


def _resolve_concern_type(turn: Any) -> str:
    return str(
        getattr(turn, "concern_type", None)
        or getattr(turn, "stance", None)
        or "general review"
    )


def _resolve_finding(turn: Any) -> str:
    return _lang.normalize_language(
        str(
            getattr(turn, "finding", None)
            or getattr(turn, "content", None)
            or ""
        )
    )


def _resolve_recommended_fix(turn: Any) -> str:
    return _lang.normalize_language(
        str(
            getattr(turn, "recommended_fix", None)
            or getattr(turn, "recommendation", None)
            or "Provider review recommended before publishing."
        )
    )


def build_review_summary(state: Any) -> list[VisibleTurn]:
    """Build the clinic-facing Authority Review Summary from state.

    Reads from state.debate (legacy field) or state.authority_review
    (preferred field). Either works — both contain the per-persona
    findings the review layer produced.
    """
    turns_raw = (
        getattr(state, "authority_review", None)
        or getattr(state, "debate", None)
        or []
    )

    winner = (
        getattr(state, "selected_recommendation", None)
        or getattr(state, "debate_winner", None)
    )
    winner_role = None
    if winner is not None:
        # Winner may be a persona object or a string role/name.
        winner_role = (
            getattr(winner, "role", None)
            or getattr(winner, "name", None)
            or (winner if isinstance(winner, str) else None)
        )

    out: list[VisibleTurn] = []
    for i, t in enumerate(turns_raw or []):
        role = _resolve_reviewer_role(t)
        eco = _normalise_ecosystem(
            getattr(getattr(t, "persona", None), "ecosystem", None)
        )
        is_winner = bool(
            winner_role
            and role
            and (
                str(winner_role).lower() == role.lower()
                or str(winner_role).lower()
                == str(getattr(getattr(t, "persona", None), "name", "")).lower()
            )
        )
        out.append(
            VisibleTurn(
                index=i,
                reviewer_role=role,
                concern_type=_resolve_concern_type(t),
                finding=_resolve_finding(t),
                recommended_fix=_resolve_recommended_fix(t),
                risk_level=_normalise_risk(getattr(t, "risk_level", None)),
                score=getattr(t, "score", None),
                is_winner=is_winner,
                selected_recommendation=is_winner,
                debug_ecosystem=eco,
                debug_ecosystem_label=_DEBUG_ECOSYSTEM_BADGE[eco]["label"],
            )
        )
    return out


def to_markdown(turns: Iterable[VisibleTurn]) -> str:
    """Clinic-facing markdown. Leads with reviewer role and risk level.

    Always ends with the standard Scrutexity disclaimer.
    """
    lines: list[str] = ["## Authority Review Summary", ""]
    for t in turns:
        marker = " — Selected Recommendation" if t.selected_recommendation else ""
        score = f" · score {t.score:.2f}" if t.score is not None else ""
        risk = _RISK_LABEL[t.risk_level]
        lines.append(
            f"**{t.reviewer_role}** _({t.concern_type} · risk {risk}{score})_{marker}"
        )
        lines.append("")
        lines.append(f"- Finding: {t.finding.strip()}")
        lines.append(f"- Recommended Fix: {t.recommended_fix.strip()}")
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return _lang.enforce_disclaimer(body)


def to_html(turns: Iterable[VisibleTurn]) -> str:
    """Clinic-facing HTML with risk-level classes. Disclaimer always appended."""
    parts: list[str] = ['<section class="authority-review">']
    parts.append("<h2>Authority Review Summary</h2>")
    for t in turns:
        sel = " authority-review__turn--selected" if t.selected_recommendation else ""
        risk_class = _RISK_CLASS[t.risk_level]
        parts.append(f'<article class="authority-review__turn{sel}">')
        parts.append(f'<strong class="authority-review__reviewer">{t.reviewer_role}</strong>')
        parts.append(
            f'<span class="authority-review__concern">{t.concern_type}</span>'
        )
        parts.append(
            f'<span class="{risk_class}">Risk: {_RISK_LABEL[t.risk_level]}</span>'
        )
        if t.score is not None:
            parts.append(
                f'<span class="authority-review__score">{t.score:.2f}</span>'
            )
        parts.append(f'<p class="authority-review__finding">{t.finding}</p>')
        parts.append(
            f'<p class="authority-review__fix">Recommended fix: {t.recommended_fix}</p>'
        )
        parts.append("</article>")
    parts.append(
        f'<footer class="authority-review__disclaimer">{_lang.DISCLAIMER}</footer>'
    )
    parts.append("</section>")
    return "".join(parts)


def attach_to_state(state: Any) -> dict:
    """LangGraph node entry point.

    Returns the state delta. Stores both the structured turns (for
    machine consumption / Owner Brief generation) and the rendered
    markdown (for direct display).
    """
    turns = build_review_summary(state)
    return {
        "authority_review_summary": [t.to_public_dict() for t in turns],
        "authority_review_summary_markdown": to_markdown(turns),
        # Legacy keys retained so older v3.0 callers do not break.
        "transcript_visible": [t.to_public_dict() for t in turns],
        "transcript_markdown": to_markdown(turns),
    }
