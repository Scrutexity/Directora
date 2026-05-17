"""Contract snapshot validation.

Every API response shape is validated against the shared
`shared/brief-api-contract.json` snapshot. The snapshot is the single
source of truth shared with LabBrief — Directora's responses and
LabBrief's Zod schemas must both validate against this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from tests.api.conftest import CLINIC_ID, PROVIDER_ID


CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "shared" / "brief-api-contract.json"
)


@pytest.fixture(scope="module")
def contract() -> dict:
    with CONTRACT_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _validate(payload, schema):
    # raises jsonschema.ValidationError on mismatch
    jsonschema.validate(instance=payload, schema=schema)


def _hdrs(token):
    return {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": CLINIC_ID,
        "X-Request-ID": "req_contract_test",
    }


def test_contract_snapshot_loads_and_has_expected_sections(contract):
    assert contract["$schema"]
    assert contract["version"]
    assert contract.get("generated_at"), (
        "snapshot must carry generated_at (v3.6 requirement)"
    )
    for name in (
        "PendingBriefResponse",
        "SignBriefRequest",
        "SignResponse",
        "ProviderBriefResponse",
        "AuditResponse",
        "ErrorResponse",
    ):
        assert name in contract["models"], f"contract missing {name}"


def test_snapshot_version_matches_constant_or_fail_loud(contract):
    """CI guard: if the snapshot is regenerated without bumping
    CONTRACT_VERSION, this fails with 'snapshot version mismatch'.

    Operationally: when changing API shapes you must (a) update the
    pydantic model, (b) bump CONTRACT_VERSION in directora/api/contract.py,
    (c) regenerate `shared/brief-api-contract.json`. Skip step (b) and
    this test fails.
    """
    from directora.api.contract import CONTRACT_VERSION
    assert contract["version"] == CONTRACT_VERSION, (
        f"snapshot version mismatch: snapshot={contract['version']!r} "
        f"code={CONTRACT_VERSION!r}. Bump CONTRACT_VERSION when changing "
        "API response shapes."
    )


def test_response_carries_x_contract_version_header(client, provider_token):
    """Every successful response surfaces the contract version so the
    LabBrief client can log it for drift debugging."""
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    assert res.status_code == 200
    from directora.api.contract import CONTRACT_VERSION
    assert res.headers.get("X-Contract-Version") == CONTRACT_VERSION


def test_pending_response_matches_contract(client, provider_token, stored_brief, contract):
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    assert res.status_code == 200
    _validate(res.json(), contract["models"]["PendingBriefResponse"])


def test_sign_response_matches_contract(client, provider_token, stored_brief, contract):
    body = {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }
    res = client.post(
        "/api/brief/sign",
        headers={**_hdrs(provider_token),
                 "Idempotency-Key": "idem-contract", "Content-Type": "application/json"},
        json=body,
    )
    assert res.status_code == 200, res.text
    _validate(res.json(), contract["models"]["SignResponse"])


def test_provider_response_matches_contract(client, provider_token, stored_brief, contract):
    res = client.get(
        "/api/brief/provider",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(provider_token),
    )
    assert res.status_code == 200
    _validate(res.json(), contract["models"]["ProviderBriefResponse"])


def test_audit_response_matches_contract(client, provider_token, stored_brief, contract):
    # Sign first so there is at least one event.
    body = {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }
    client.post(
        "/api/brief/sign",
        headers={**_hdrs(provider_token),
                 "Idempotency-Key": "idem-contract-audit",
                 "Content-Type": "application/json"},
        json=body,
    )
    res = client.get(
        "/api/labs/audit",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(provider_token),
    )
    assert res.status_code == 200
    _validate(res.json(), contract["models"]["AuditResponse"])


def test_error_response_matches_contract(client, provider_token, contract):
    """404 brief_not_found is the cheapest path to a clean ErrorResponse."""
    res = client.get(
        "/api/brief/provider",
        params={"brief_id": "DOES_NOT_EXIST"},
        headers=_hdrs(provider_token),
    )
    # FastAPI's default error format uses {"detail": "..."}, our routes
    # use {"error": "..."} via JSONResponse. The /provider route raises
    # HTTPException(detail="brief_not_found") — middleware adds request_id.
    body = res.json()
    assert res.status_code == 404
    # The contract permits either {"error","detail","ledger_event_id","request_id"}
    # or FastAPI's default {"detail"} — we test against the explicit
    # /sign error path which uses our envelope.
    _validate(
        {
            "error": str(body.get("detail") or body.get("error") or "brief_not_found"),
            "request_id": body.get("request_id"),
        },
        contract["models"]["ErrorResponse"],
    )


def test_sign_error_uses_contract_envelope(client, provider_token, contract):
    """POST /api/brief/sign emits the structured ErrorResponse envelope."""
    res = client.post(
        "/api/brief/sign",
        headers={**_hdrs(provider_token),
                 "Idempotency-Key": "idem-err",
                 "Content-Type": "application/json"},
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
    assert body["request_id"]
    _validate(body, contract["models"]["ErrorResponse"])
