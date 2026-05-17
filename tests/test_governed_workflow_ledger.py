"""Governed Workflow Ledger tests (refactored outcome telemetry)."""
from __future__ import annotations

import pytest

from directora.telemetry import outcome


@pytest.fixture
def state():
    class S:
        run_id = "run-test"
        tier = "quality"
        clinic_name = "Example Aesthetics NYC"
        treatment = "Morpheus8"
        market = "Upper East Side, NYC"
        approval_status = "human approval required"
        telemetry = {"events": []}
    return S()


def test_claim_risk_event_records(memory_ledger, state):
    outcome.record_outcome(
        state,
        kind="claim_risk_flagged",
        risk_level="high",
        reason="Guaranteed outcome language detected",
    )
    events = memory_ledger.read_all()
    assert len(events) == 1
    e = events[0]
    assert e.kind == "claim_risk_flagged"
    assert e.risk_level == "high"
    assert e.clinic_name == "Example Aesthetics NYC"
    assert e.treatment == "Morpheus8"


def test_human_approval_required_event_records(memory_ledger, state):
    outcome.record_outcome(
        state,
        kind="human_approval_required",
        approval_status="human approval required",
        reason="High-risk medical aesthetics asset",
    )
    events = memory_ledger.read_all()
    assert len(events) == 1
    assert events[0].kind == "human_approval_required"
    assert events[0].approval_status == "human approval required"


def test_telemetry_failure_never_raises(memory_ledger):
    class Broken:
        # __getattr__ raising would crash naive callers
        def __getattr__(self, name):
            raise RuntimeError("nope")
    # Must not raise.
    outcome.record_outcome(Broken(), kind="asset_drafted")


def test_summary_includes_risk_approval_render_and_treatments(
    memory_ledger, state
):
    outcome.record_outcome(state, kind="claim_risk_flagged", risk_level="high")
    outcome.record_outcome(state, kind="claim_risk_flagged", risk_level="low")
    outcome.record_outcome(state, kind="human_approval_required")
    outcome.record_outcome(state, kind="render_fallback", engine="happyhorse")
    outcome.record_outcome(state, kind="render_ok", engine="seedance",
                           latency_s=2.0)
    summary = outcome.summarise(run_id="run-test")
    assert summary["claim_risk_count"] == 2
    assert summary["human_approval_required_count"] == 1
    assert summary["render_fallback_count"] == 1
    assert "Morpheus8" in summary["treatments_processed"]
    assert summary["by_kind"]["claim_risk_flagged"] == 2
    assert summary["total_latency_s"] == 2.0


def test_state_telemetry_bucket_receives_events(memory_ledger, state):
    outcome.record_outcome(state, kind="asset_drafted",
                           extra_field="short_form_script")
    assert state.telemetry["events"][0]["kind"] == "asset_drafted"
    assert state.telemetry["events"][0]["extra"]["extra_field"] == "short_form_script"


def test_finalize_node_attaches_summary(memory_ledger, state):
    outcome.record_outcome(state, kind="export_completed")
    delta = outcome.finalize_node(state)
    assert delta["telemetry"]["summary"]["event_count"] == 1


def test_jsonl_sink_roundtrip(tmp_path, state):
    sink = outcome.JsonlSink(tmp_path / "ledger.jsonl")
    outcome.reset_sink_for_tests(sink)
    outcome.record_outcome(state, kind="owner_brief_ready")
    raw = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    assert len(raw) == 1
    outcome.reset_sink_for_tests(None)


def test_all_documented_event_kinds_supported(memory_ledger, state):
    for kind in outcome.EVENT_KINDS:
        outcome.record_outcome(state, kind=kind)
    summary = outcome.summarise(run_id="run-test")
    # Every canonical kind appears in the histogram.
    for kind in outcome.EVENT_KINDS:
        assert summary["by_kind"].get(kind, 0) >= 1
