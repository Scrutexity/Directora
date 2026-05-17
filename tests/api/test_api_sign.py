"""POST /api/brief/sign tests — happy path, error matrix, atomicity."""
from __future__ import annotations

import pytest

from tests.api.conftest import (
    CLINIC_ID,
    OTHER_CLINIC_ID,
    PROVIDER_ID,
    _seeded_brief,
)
from directora.scrutexity import brief_store as bs
from directora.scrutexity.brief_store import BriefStatus
from directora.telemetry import outcome as ledger_module


def _hdrs(token, *, idem="sign-BRF_TEST_01-attempt-1", clinic_id=CLINIC_ID):
    return {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": clinic_id,
        "X-Request-ID": "req_test_sign",
        "Idempotency-Key": idem,
        "Content-Type": "application/json",
    }


def _body(brief_id: str = "BRF_TEST_01", value: str = "Dr Jane Doe"):
    return {
        "brief_id": brief_id,
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": value,
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {
            "app": "labbrief",
            "version": "2.5.0",
            "session_id": "sess_abc",
        },
    }


def test_sign_happy_path(client, provider_token, stored_brief):
    res = client.post("/api/brief/sign", headers=_hdrs(provider_token), json=_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "signed"
    assert body["ledger_event_id"].startswith("evt_")
    assert body["brief_content_hash"] == stored_brief.brief_content_hash
    assert body["binding_hash"]
    assert body["next_actions"]["export"].startswith("/api/brief/provider")
    rec = bs.get_brief_store().get("BRF_TEST_01")
    assert rec.status == BriefStatus.SIGNED
    kinds = [e.kind for e in ledger_module.get_sink().read_all()]
    assert "provider_brief_signed" in kinds


def test_sign_rejects_unknown_brief(client, provider_token):
    res = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token),
        json=_body("BRF_MISSING"),
    )
    assert res.status_code == 404
    assert res.json()["error"] == "brief_not_found"


def test_sign_rejects_already_signed_with_event_id(client, provider_token, stored_brief):
    first = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="sign-first"),
        json=_body(),
    )
    assert first.status_code == 200
    ev = first.json()["ledger_event_id"]
    second = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, idem="sign-second"),
        json=_body(),
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "already_signed"
    assert body["ledger_event_id"] == ev


def test_sign_rejects_invalid_status(client, provider_token):
    rec = _seeded_brief()
    rec.status = "drafted"  # not pending_review
    bs.get_brief_store().put(rec)
    res = client.post("/api/brief/sign", headers=_hdrs(provider_token), json=_body())
    assert res.status_code == 409
    assert res.json()["error"] == "invalid_status"


def test_sign_rejects_other_clinic(client, other_clinic_token, stored_brief):
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(other_clinic_token, clinic_id=OTHER_CLINIC_ID),
        json=_body(),
    )
    assert res.status_code == 403


def test_sign_rejects_unassigned_provider_without_director_role(
    client, stored_brief
):
    from directora.api.auth import encode_stub_token
    foreign = encode_stub_token("PRV_NOT_ASSIGNED", CLINIC_ID, roles=("provider",))
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(foreign),
        json={**_body(), "provider_id": "PRV_NOT_ASSIGNED"},
    )
    assert res.status_code == 403
    assert res.json()["error"] == "permission_denied"


def test_sign_allows_medical_director(client, director_token, stored_brief):
    res = client.post(
        "/api/brief/sign",
        headers=_hdrs(director_token),
        json=_body(),
    )
    assert res.status_code == 200


def test_sign_rejects_missing_idempotency_key(client, provider_token, stored_brief):
    hdrs = {
        "Authorization": f"Bearer {provider_token}",
        "X-Clinic-ID": CLINIC_ID,
    }
    res = client.post("/api/brief/sign", headers=hdrs, json=_body())
    assert res.status_code == 400
    assert res.json()["error"] == "missing_idempotency_key"


def test_sign_rejects_stale_engine_run_id(client, provider_token, stored_brief):
    body = _body()
    body["engine_run_id"] = "different-run"
    res = client.post("/api/brief/sign", headers=_hdrs(provider_token), json=body)
    assert res.status_code == 409
    body_out = res.json()
    assert body_out["error"] == "invalid_status"
    assert body_out["detail"] == "stale_engine_context"


def test_sign_rejects_blank_signature(client, provider_token, stored_brief):
    res = client.post(
        "/api/brief/sign", headers=_hdrs(provider_token),
        json=_body(value="     "),
    )
    assert res.status_code == 422


def test_sign_rejects_brief_missing_content_hash(client, provider_token):
    rec = _seeded_brief()
    rec.brief_content_hash = None
    rec.provider_brief_canonical_json = None
    bs.get_brief_store().put(rec)
    res = client.post("/api/brief/sign", headers=_hdrs(provider_token), json=_body())
    assert res.status_code == 500
    assert res.json()["error"] == "engine_or_ledger_failure"
