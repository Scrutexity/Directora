"""GET /api/labs/audit and GET /api/brief/provider tests."""
from __future__ import annotations

import pytest

from tests.api.conftest import CLINIC_ID, PROVIDER_ID


def _hdrs(token, *, clinic=CLINIC_ID):
    return {"Authorization": f"Bearer {token}", "X-Clinic-ID": clinic}


def _sign_headers(token):
    return {
        **_hdrs(token),
        "Idempotency-Key": "idem-audit",
        "Content-Type": "application/json",
    }


def _sign_body():
    return {
        "brief_id": "BRF_TEST_01",
        "provider_id": PROVIDER_ID,
        "signature": {
            "method": "typed",
            "value": "Dr Jane Doe",
            "signed_at": "2026-05-16T17:01:33Z",
        },
        "client": {"app": "labbrief", "version": "2.5.0", "session_id": "s"},
    }


def test_audit_returns_only_brief_scoped_events(client, provider_token, stored_brief):
    # No events yet.
    res = client.get(
        "/api/labs/audit",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(provider_token),
    )
    assert res.status_code == 200
    assert res.json()["events"] == []

    # Sign — this emits provider_brief_signed tagged with brief_id.
    sign = client.post(
        "/api/brief/sign",
        headers=_sign_headers(provider_token),
        json=_sign_body(),
    )
    assert sign.status_code == 200

    res = client.get(
        "/api/labs/audit",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(provider_token),
    )
    body = res.json()
    assert body["brief_id"] == "BRF_TEST_01"
    kinds = [e["kind"] for e in body["events"]]
    assert "provider_brief_signed" in kinds


def test_audit_404_when_brief_missing(client, provider_token):
    res = client.get(
        "/api/labs/audit", params={"brief_id": "NO"}, headers=_hdrs(provider_token),
    )
    assert res.status_code == 404


def test_provider_returns_canonical_snippet_and_hash(client, provider_token, stored_brief):
    res = client.get(
        "/api/brief/provider",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(provider_token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["asset_type"] == "provider_brief_snippet"
    assert body["brief_content_hash"] == stored_brief.brief_content_hash
    assert body["canonical_json"] == stored_brief.provider_brief_canonical_json
    assert body["snippet"]["treatment"] == "Morpheus8"


def test_provider_404_when_missing(client, provider_token):
    res = client.get(
        "/api/brief/provider", params={"brief_id": "NO"}, headers=_hdrs(provider_token),
    )
    assert res.status_code == 404


def test_provider_rejects_cross_clinic(client, other_clinic_token, stored_brief):
    res = client.get(
        "/api/brief/provider",
        params={"brief_id": "BRF_TEST_01"},
        headers=_hdrs(other_clinic_token, clinic="CLN_OTHER"),
    )
    assert res.status_code == 403
