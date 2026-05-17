"""Observability middleware tests — X-Request-ID propagation + error body injection."""
from __future__ import annotations

import pytest

from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token, *, request_id: str | None = None):
    h = {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": CLINIC_ID,
    }
    if request_id:
        h["X-Request-ID"] = request_id
    return h


def test_response_header_echoes_provided_request_id(client, provider_token):
    rid = "req_caller_provided_abc"
    res = client.get(
        "/api/brief/pending", headers=_hdrs(provider_token, request_id=rid)
    )
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == rid


def test_response_header_generates_request_id_when_absent(client, provider_token):
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    assert res.status_code == 200
    rid = res.headers.get("X-Request-ID")
    assert rid is not None
    assert rid.startswith("req_")


def test_error_response_includes_request_id_in_body(client, provider_token):
    res = client.post(
        "/api/brief/sign",
        headers={
            **_hdrs(provider_token, request_id="req_err_test"),
            "Idempotency-Key": "idem-x",
            "Content-Type": "application/json",
        },
        json={
            "brief_id": "DOES_NOT_EXIST",
            "provider_id": PROVIDER_ID,
            "signature": {
                "method": "typed", "value": "x",
                "signed_at": "2026-05-16T17:01:33Z",
            },
            "client": {"app": "labbrief", "version": "1.0.0", "session_id": "s"},
        },
    )
    assert res.status_code == 404
    body = res.json()
    assert body["error"] == "brief_not_found"
    assert body["request_id"] == "req_err_test"
    # Header echo too.
    assert res.headers.get("X-Request-ID") == "req_err_test"


def test_default_validation_error_also_includes_request_id(client, provider_token):
    """FastAPI's own 422 for missing fields should still get request_id."""
    res = client.post(
        "/api/brief/sign",
        headers={
            **_hdrs(provider_token, request_id="req_validation"),
            "Idempotency-Key": "idem-v",
            "Content-Type": "application/json",
        },
        json={"brief_id": "x"},  # missing provider_id, signature, client
    )
    assert res.status_code == 422
    body = res.json()
    assert body["request_id"] == "req_validation"
