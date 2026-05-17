"""Ledger event schema tests.

v3.7 correction: there is NO `provider_brief_signed_rollback` kind.
Finalize failures are recorded as a neutral note
(`provider_brief_finalize_failed`) — the ledger never frames anything
as a compensation or rollback.
"""
from __future__ import annotations

import pytest

from directora.telemetry import outcome as ledger


def test_provider_brief_signed_in_event_kinds():
    assert "provider_brief_signed" in ledger.EVENT_KINDS


def test_finalize_failed_event_in_event_kinds():
    """v3.7: neutral failure note replaces the legacy rollback kind."""
    assert "provider_brief_finalize_failed" in ledger.EVENT_KINDS


def test_rollback_event_kind_does_not_exist():
    """Explicit assertion that the legacy kind is gone."""
    assert "provider_brief_signed_rollback" not in ledger.EVENT_KINDS


def test_event_records_full_sign_schema():
    sink = ledger.MemorySink()
    ledger.reset_sink_for_tests(sink)
    try:
        class S:
            run_id = "run-x"
            telemetry = {"events": []}
        eid = ledger.record_outcome(
            S(),
            kind="provider_brief_signed",
            clinic_id="CLN",
            provider_id="PRV",
            brief_id="BRF",
            treatment="Morpheus8",
            market="Upper East Side, NYC",
            approval_status="signed",
            engine_run_id="run-x",
            authority_brief_version="1",
            provider_brief_version="1",
            signature_method="typed",
            signature_value_hash="b" * 64,
            binding_hash="c" * 64,
            brief_content_hash="a" * 64,
            signed_at="2026-05-16T17:01:33.000Z",
            correlation_request_id="req-1",
            correlation_idempotency_key="idem-1",
            patient_ref="P_REF_001",
            encounter_ref="E_REF_001",
        )
        assert eid and eid.startswith("evt_")
        events = sink.read_all()
        assert len(events) == 1
        e = events[0]
        assert e.kind == "provider_brief_signed"
        assert e.event_id == eid
        assert e.clinic_id == "CLN"
        assert e.provider_id == "PRV"
        assert e.brief_id == "BRF"
        assert e.extra["brief_content_hash"] == "a" * 64
        assert e.extra["binding_hash"] == "c" * 64
        assert e.extra["correlation_idempotency_key"] == "idem-1"
    finally:
        ledger.reset_sink_for_tests(None)


def test_audit_lookup_filters_by_brief_id():
    sink = ledger.MemorySink()
    ledger.reset_sink_for_tests(sink)
    try:
        class S:
            run_id = "r"
            telemetry = {"events": []}
        ledger.record_outcome(S(), kind="asset_drafted", brief_id="BRF_A")
        ledger.record_outcome(S(), kind="asset_drafted", brief_id="BRF_B")
        ledger.record_outcome(S(), kind="provider_brief_signed", brief_id="BRF_A")
        a_events = ledger.list_events_for_brief("BRF_A")
        b_events = ledger.list_events_for_brief("BRF_B")
        assert {e["kind"] for e in a_events} == {"asset_drafted", "provider_brief_signed"}
        assert {e["kind"] for e in b_events} == {"asset_drafted"}
    finally:
        ledger.reset_sink_for_tests(None)
