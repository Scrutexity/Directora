"""Idempotency replay and conflict tests for POST /api/brief/sign."""
from __future__ import annotations

import pytest

from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token, idem):
    return {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": CLINIC_ID,
        "Idempotency-Key": idem,
        "X-Request-ID": "req_test",
        "Content-Type": "application/json",
    }


def _body(value="Dr Jane Doe"):
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": value,
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }


def test_replay_same_key_same_body_returns_stored_response(
    client, provider_token, stored_brief
):
    res1 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-1"),
        json=_body(),
    )
    assert res1.status_code == 200
    body1 = res1.json()

    res2 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-1"),
        json=_body(),
    )
    # Same key, same body — must replay byte-identically.
    assert res2.status_code == 200
    assert res2.json() == body1


def test_conflict_same_key_different_body(client, provider_token, stored_brief):
    res1 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-2"),
        json=_body(value="Dr Jane Doe"),
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-2"),
        json=_body(value="Dr Other Person"),
    )
    assert res2.status_code == 409
    assert res2.json()["error"] == "idempotency_conflict"


def test_different_keys_allow_separate_attempts(client, provider_token, stored_brief):
    """Different idempotency keys are distinct attempts — the second must
    hit already_signed, not replay or conflict."""
    res1 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-A"),
        json=_body(),
    )
    assert res1.status_code == 200
    res2 = client.post(
        "/api/brief/sign",
        headers=_hdrs(provider_token, "idem-B"),
        json=_body(),
    )
    assert res2.status_code == 409
    assert res2.json()["error"] == "already_signed"
