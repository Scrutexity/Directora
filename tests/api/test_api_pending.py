"""GET /api/brief/pending tests."""
from __future__ import annotations

import pytest

from tests.api.conftest import (
    CLINIC_ID,
    OTHER_CLINIC_ID,
    OTHER_PROVIDER_ID,
    PROVIDER_ID,
    _seeded_brief,
)
from directora.scrutexity import brief_store as bs
from directora.scrutexity.brief_store import BriefStatus


def _hdrs(token, clinic_id=CLINIC_ID):
    return {
        "Authorization": f"Bearer {token}",
        "X-Clinic-ID": clinic_id,
        "X-Request-ID": "req_test_1",
    }


def test_pending_empty_returns_no_items(client, provider_token):
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    assert res.status_code == 200
    assert res.json() == {"items": [], "next_cursor": None}


def test_pending_returns_seeded_brief_with_links(client, provider_token, stored_brief):
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["brief_id"] == "BRF_TEST_01"
    assert item["status"] == "pending_review"
    assert item["links"]["audit"] == f"/api/labs/audit?brief_id={item['brief_id']}"
    assert item["engine_outputs"]["provider_brief_preview"]["headline"]


def test_pending_excludes_signed_briefs(client, provider_token):
    pending = _seeded_brief("BRF_PEND")
    signed = _seeded_brief("BRF_SIGNED")
    signed.status = BriefStatus.SIGNED
    bs.get_brief_store().put(pending)
    bs.get_brief_store().put(signed)
    res = client.get("/api/brief/pending", headers=_hdrs(provider_token))
    ids = [item["brief_id"] for item in res.json()["items"]]
    assert "BRF_PEND" in ids
    assert "BRF_SIGNED" not in ids


def test_pending_filters_to_principals_clinic(client, other_clinic_token):
    bs.get_brief_store().put(_seeded_brief("BRF_OURS"))
    bs.get_brief_store().put(_seeded_brief(
        "BRF_THEIRS",
        clinic_id=OTHER_CLINIC_ID,
        provider_id=OTHER_PROVIDER_ID,
    ))
    res = client.get(
        "/api/brief/pending",
        headers=_hdrs(other_clinic_token, clinic_id=OTHER_CLINIC_ID),
    )
    ids = [item["brief_id"] for item in res.json()["items"]]
    assert ids == ["BRF_THEIRS"]


def test_pending_rejects_cross_provider_listing_for_non_director(
    client, provider_token
):
    res = client.get(
        "/api/brief/pending",
        params={"provider_id": OTHER_PROVIDER_ID},
        headers=_hdrs(provider_token),
    )
    assert res.status_code == 403


def test_pending_allows_cross_provider_for_medical_director(
    client, director_token
):
    bs.get_brief_store().put(_seeded_brief("BRF_X"))
    res = client.get(
        "/api/brief/pending",
        params={"provider_id": PROVIDER_ID},
        headers=_hdrs(director_token),
    )
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1


def test_pending_requires_bearer_token(client):
    res = client.get("/api/brief/pending")
    assert res.status_code == 401
