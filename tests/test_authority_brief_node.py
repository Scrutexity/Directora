"""End-to-end test for the authority_brief LangGraph node and the
owner_brief LangGraph node — ensures the Scrutexity flow records ledger
events and surfaces the right state deltas."""
from __future__ import annotations

from directora.nodes import authority_brief_node, owner_brief_node
from directora.telemetry import outcome


class _State:
    def __init__(self, **kwargs):
        self.run_id = "run-test"
        self.tier = "fast"
        self.clinic_name = None
        self.treatment = None
        self.market = None
        self.approval_status = None
        self.receipt_input = None
        self.clinic_context = None
        self.authority_brief = None
        self.telemetry = {"events": []}
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_generic_mode_when_receipt_missing(memory_ledger):
    state = _State()
    delta = authority_brief_node.run(state)
    assert delta["mode"] == "generic"
    assert delta["authority_brief"] is None
    # No ledger events recorded.
    assert memory_ledger.read_all() == []


def test_scrutexity_mode_emits_brief_and_ledger_event(
    memory_ledger, sample_receipt, sample_clinic_context
):
    state = _State(
        receipt_input=sample_receipt,
        clinic_context=sample_clinic_context,
    )
    delta = authority_brief_node.run(state)
    assert delta["mode"] == "scrutexity"
    assert delta["authority_brief"]["treatment"] == "Morpheus8"
    assert delta["clinic_name"] == "Example Aesthetics NYC"
    assert delta["approval_status"] == "human approval required"
    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "authority_brief_created" in kinds


def test_owner_brief_node_uses_ledger_summary(
    memory_ledger, sample_receipt, sample_clinic_context
):
    state = _State(
        receipt_input=sample_receipt, clinic_context=sample_clinic_context
    )
    brief_delta = authority_brief_node.run(state)
    state.authority_brief = brief_delta["authority_brief"]
    # Simulate some upstream events.
    outcome.record_outcome(state, kind="asset_drafted", treatment="Morpheus8")
    outcome.record_outcome(state, kind="claim_risk_flagged",
                           risk_level="medium", treatment="Morpheus8")
    delta = owner_brief_node.run(state)
    snippet = delta["owner_brief"]
    assert snippet["asset_type"] == "owner_brief_snippet"
    assert snippet["ledger_counts"]["claim_risk_flagged"] == 1
    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "owner_brief_ready" in kinds


def test_owner_brief_node_noop_in_generic_mode(memory_ledger):
    state = _State()
    delta = owner_brief_node.run(state)
    assert delta["owner_brief"] is None


def test_malformed_receipt_records_receipt_invalid_event(memory_ledger):
    """Strict mode: an invalid receipt produces a structured error state
    and a ledger event of kind 'receipt_invalid'. No exception escapes
    the node."""
    bad_receipt = {
        # Missing clinic_name, market, primary_visibility_gap, first_fix...
        "treatment": "Morpheus8",
    }
    state = _State(receipt_input=bad_receipt)
    delta = authority_brief_node.run(state)
    assert delta["mode"] == "error"
    assert delta["authority_brief"] is None
    assert delta["authority_brief_validation"]["ok"] is False
    assert "receipt_validation_error" in delta
    assert delta["approval_status"] == "blocked: receipt validation failed"

    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "receipt_invalid" in kinds
    assert "authority_brief_created" not in kinds


def test_ambiguous_treatments_records_receipt_invalid(memory_ledger):
    """The exact shape of the Elite Aesthetics NYC receipt without an
    explicit `treatment` field must error structurally, not guess."""
    bad_receipt = {
        "clinic_name": "Elite Aesthetics NYC",
        "market": "Upper East Side, NYC",
        "treatments_tested": ["Morpheus8", "lip filler", "Botox"],
        "primary_visibility_gap": "Did not surface in this prompt set",
        "first_fix_id_prioritize": "Provider-led content.",
    }
    state = _State(receipt_input=bad_receipt)
    delta = authority_brief_node.run(state)
    assert delta["mode"] == "error"
    assert any(
        "Ambiguous" in str(e) or "treatment" in str(e).lower()
        for e in delta["authority_brief_validation"]["errors"]
    )
    kinds = [e.kind for e in memory_ledger.read_all()]
    assert "receipt_invalid" in kinds


def test_ledger_summary_includes_receipt_invalid_count(memory_ledger):
    bad_receipt = {"treatment": "Morpheus8"}
    state = _State(receipt_input=bad_receipt)
    authority_brief_node.run(state)
    from directora.telemetry import outcome as ledger
    summary = ledger.summarise(run_id="run-test")
    assert summary["receipt_invalid_count"] == 1


def test_strict_disabled_via_state_flag(memory_ledger, sample_receipt):
    """Legacy / migration: state.strict_receipt=False lets a malformed
    receipt fall back to best-effort defaulting."""
    # Strip a required field but disable strict mode.
    sample_receipt.pop("first_fix_id_prioritize")
    state = _State(receipt_input=sample_receipt)
    state.strict_receipt = False  # type: ignore[attr-defined]
    delta = authority_brief_node.run(state)
    # In lenient mode, build_authority_brief fills the gap with a default.
    assert delta["mode"] == "scrutexity"
    assert delta["authority_brief"] is not None
