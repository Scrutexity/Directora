"""LangGraph node that produces the Weekly Owner Brief snippet from the
Authority Brief plus the current Governed Workflow Ledger summary.
"""
from __future__ import annotations

from typing import Any

from directora.scrutexity import export as _export
from directora.telemetry.outcome import record_outcome, summarise


def run(state: Any) -> dict:
    brief = getattr(state, "authority_brief", None)
    if not brief:
        # Generic mode — owner brief is a no-op.
        return {"owner_brief": None}

    run_id = getattr(state, "run_id", None)
    ledger_summary = summarise(run_id)
    owner_brief = _export.render_owner_brief(brief, ledger_summary)

    record_outcome(
        state,
        kind="owner_brief_ready",
        clinic_name=brief.get("clinic_name"),
        treatment=brief.get("treatment"),
        market=brief.get("market"),
        approval_status=owner_brief.get("human_approval_status"),
    )
    return {"owner_brief": owner_brief}
