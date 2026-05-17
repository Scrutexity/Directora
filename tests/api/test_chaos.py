"""Chaos switch tests — atomicity, backpressure, contract drift.

These tests prove three things the production system depends on:

    1. FAULT_LEDGER_APPEND → record_outcome returns None and the brief
       sign-off rolls back cleanly. No 200, no signed status, no ledger
       row for the loser of the race.

    2. FAULT_DB_LOCK → IdempotencyStore raises IdempotencyStoreBusy
       which the /sign route translates to 503 with Retry-After: 1
       (and not 500).

    3. FAULT_CONTRACT_MISMATCH → response shapes drop required fields
       and the contract validation test catches them. We verify
       behaviour by directly calling the validator with a malformed
       payload — proves the drift gate works.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from directora.scrutexity.brief_store import BriefStatus
from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token, *, idem=None):
    h = {"Authorization": f"Bearer {token}", "X-Clinic-ID": CLINIC_ID}
    if idem:
        h["Idempotency-Key"] = idem
        h["Content-Type"] = "application/json"
    return h


def _sign_body():
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed", "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }


def test_ledger_failure_does_not_sign_brief(
    monkeypatch, client, provider_token, stored_brief,
):
    """Atomicity: if record_outcome fails (chaos injected), the brief
    must stay in pending_review and no /sign 200 is returned."""
    monkeypatch.setenv("FAULT_LEDGER_APPEND", "1")
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-fault-1"),
        json=_sign_body(),
    )
    assert res.status_code == 500
    assert res.json()["error"] == "engine_or_ledger_failure"

    # Brief store is untouched — status is still pending_review.
    from directora.scrutexity.brief_store import get_brief_store
    rec = get_brief_store().get("BRF_TEST_01")
    assert rec is not None
    assert rec.status == BriefStatus.PENDING_REVIEW
    assert rec.ledger_event_id is None


def test_db_lock_returns_503_with_retry_after(
    monkeypatch, client, provider_token, stored_brief,
):
    """SQLite busy → 503 + Retry-After: 1, never 500."""
    # Replace the global idempotency store with a SQLite store so
    # FAULT_DB_LOCK actually fires inside begin().
    import tempfile
    from directora.api import idempotency as idem_module
    from directora.api.idempotency_store import SQLiteIdempotencyStore

    with tempfile.TemporaryDirectory() as tmp:
        sql = SQLiteIdempotencyStore(db_path=f"{tmp}/idem.db")
        idem_module.reset_store_for_tests(sql)
        try:
            monkeypatch.setenv("FAULT_DB_LOCK", "1")
            res = client.post(
                "/api/brief/sign",
                headers=_hdrs(provider_token, idem="idem-busy-1"),
                json=_sign_body(),
            )
            assert res.status_code == 503
            assert res.headers.get("Retry-After") == "1"
            body = res.json()
            assert body["error"] == "idempotency_store_busy"
        finally:
            idem_module.reset_store_for_tests(None)


def test_contract_validator_catches_missing_required_fields():
    """Drift gate: if Directora ever omits a required field, the
    snapshot validator must reject the response.

    This simulates FAULT_CONTRACT_MISMATCH by hand-rolling a malformed
    payload and feeding it to the validator.
    """
    snapshot_path = (
        Path(__file__).resolve().parents[2]
        / "shared" / "brief-api-contract.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    schema = snapshot["models"]["SignResponse"]
    bad_payload = {
        # Missing `status`, `signed_at`, `binding_hash` etc.
        "ledger_event_id": "evt_x",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad_payload, schema)


def test_x_idempotency_replayed_header_on_replay(
    client, provider_token, stored_brief,
):
    """Byte-identical replay surfaces X-Idempotency-Replayed: true header."""
    first = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-replay-x"),
        json=_sign_body(),
    )
    assert first.status_code == 200
    second = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-replay-x"),
        json=_sign_body(),
    )
    assert second.status_code == 200
    assert second.headers.get("X-Idempotency-Replayed") == "true"
    assert second.json() == first.json()


def test_first_call_does_not_carry_replay_header(
    client, provider_token, stored_brief,
):
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="idem-first"),
        json=_sign_body(),
    )
    assert res.status_code == 200
    # Replay header is opt-in on replay only.
    assert res.headers.get("X-Idempotency-Replayed") is None
