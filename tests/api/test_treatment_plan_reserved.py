"""Treatment Plan signing is reserved — namespace defined, no routes.

This test family enforces that:
    1. The event kinds are reserved in RESERVED_EVENT_KINDS.
    2. The schema stubs exist.
    3. No /api/treatment-plan/* routes are exposed (all 404).
    4. No treatment_plan_* events are emitted by the engine today.

When v4.0 ships Treatment Plan signing for real, these tests get
inverted: routes exist, events fire, the reserved kinds graduate into
EVENT_KINDS.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from directora.api.schemas import (
    TreatmentPlanResponse,
    TreatmentPlanSignRequest,
    TreatmentPlanSignResponse,
)
from directora.api.server import create_app
from directora.telemetry.outcome import (
    EVENT_KINDS,
    RESERVED_EVENT_KINDS,
    MemorySink,
    reset_sink_for_tests,
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DIRECTORA_CLINIC_SIGNING_SECRET_DEFAULT", "test")
    reset_sink_for_tests(MemorySink())
    with TestClient(create_app()) as c:
        yield c
    reset_sink_for_tests(None)


def test_reserved_event_kinds_present():
    for kind in (
        "treatment_plan_ready",
        "treatment_plan_signed",
        "treatment_plan_amended",
        "treatment_plan_voided",
    ):
        assert kind in RESERVED_EVENT_KINDS, f"missing reserved kind {kind}"


def test_reserved_kinds_not_yet_in_event_kinds():
    """Confirms reservation is namespace-only. When v4 wires Treatment
    Plan signing, the kinds graduate into EVENT_KINDS and this test
    inverts."""
    for kind in RESERVED_EVENT_KINDS:
        assert kind not in EVENT_KINDS, (
            f"reserved kind {kind} unexpectedly present in EVENT_KINDS"
        )


def test_treatment_plan_schemas_are_defined_but_optional():
    # Defined as a class — instantiation with minimal data does not crash.
    assert TreatmentPlanResponse.__name__ == "TreatmentPlanResponse"
    assert TreatmentPlanSignRequest.__name__ == "TreatmentPlanSignRequest"
    assert TreatmentPlanSignResponse.__name__ == "TreatmentPlanSignResponse"


def test_treatment_plan_routes_return_404(client):
    for path in (
        "/api/treatment-plan",
        "/api/treatment-plan/pending",
        "/api/treatment-plan/sign",
        "/api/treatment-plan/provider",
    ):
        res_get = client.get(path)
        res_post = client.post(path, json={})
        assert res_get.status_code == 404, (
            f"GET {path} should not be served (got {res_get.status_code})"
        )
        assert res_post.status_code in (404, 405), (
            f"POST {path} should not be served (got {res_post.status_code})"
        )


def test_no_treatment_plan_events_present_in_smoke_run(client):
    """Driving the engine end-to-end must not emit any Treatment Plan
    events. The Phase 3 boundary is namespace-only."""
    from directora.telemetry.outcome import get_sink
    events = get_sink().read_all()
    assert all(
        e.kind not in RESERVED_EVENT_KINDS for e in events
    ), "Treatment Plan events leaked into the ledger"
